// Rating page: optimistic UI, keyboard shortcuts, retry queue and poster preloading.
import { getJSON, postJSON, toast } from "./api.js";
import { keyToAction } from "./keys.js";
import { Preloader, RatingSession, RetryQueue } from "./queue.js";

const $ = (id) => document.getElementById(id);
const card = $("card");
const empty = $("empty");
const retryBox = $("retry");
const scoreButtons = [...document.querySelectorAll("#score-buttons .score")];
const images = new Map();

const preloader = new Preloader({
  count: 5,
  load: (url) => {
    const img = new Image();
    img.decoding = "async";
    img.src = url;
    images.set(url, img);
  },
});

const session = new RatingSession({
  blockSize: 20,
  refillBelow: 10,
  preloader,
  fetchBlock: async (limit) => {
    const data = await getJSON(`/api/queue?limit=${limit}`);
    if (!queue.size) setProgress(data.progress);
    return data.items;
  },
});

let progress = { rated: 0, not_seen: 0, remaining: 0, total: 0 };

const URLS = { rate: "/api/rate", not_seen: "/api/not-seen", later: "/api/later", undo: "/api/undo" };
const newId = () =>
  (globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);

const queue = new RetryQueue({
  send: async (request) => {
    // keepalive lets an in-flight request finish even if the page is closed meanwhile.
    const data = await postJSON(URLS[request.type], request.body, { keepalive: true });
    if (data && data.progress && queue.size <= 1) setProgress(data.progress);
    if (data && data.recompute_started) toast("Empfehlungen werden im Hintergrund neu berechnet …");
    return true;
  },
  onChange: ({ pending, failures, lastError }) => {
    if (failures > 0) {
      retryBox.hidden = false;
      retryBox.textContent = `${pending} Aktion(en) noch nicht gespeichert (${lastError}). Neuer Versuch läuft automatisch …`;
      retryBox.onclick = () => queue.retryNow();
    } else {
      retryBox.hidden = true;
    }
  },
});

function setProgress(p) {
  progress = { ...p };
  renderProgress();
}

function renderProgress() {
  const { rated, not_seen: notSeen, remaining, total } = progress;
  $("progress-text").textContent = `${rated} bewertet · ${notSeen} nicht gesehen · ${remaining} übrig`;
  const done = total ? Math.min(100, Math.round(((total - remaining) / total) * 100)) : 0;
  $("progress-fill").style.width = `${done}%`;
}

function render() {
  const item = session.current;
  if (!item) {
    card.hidden = true;
    empty.hidden = false;
    return;
  }
  card.hidden = false;
  empty.hidden = true;
  const poster = $("poster");
  const cached = images.get(item.poster_url);
  poster.src = cached && cached.complete ? cached.src : item.poster_url;
  poster.alt = `Poster: ${item.title}`;
  $("film-title").textContent = item.title;
  $("film-original").textContent = item.original_title || "";
  const meta = [item.year, item.runtime ? `${item.runtime} Min.` : null, (item.genres || []).join(", ")];
  $("film-meta").textContent = meta.filter(Boolean).join(" · ");
  const hints = $("film-hints");
  hints.replaceChildren(
    ...(item.hints || []).map((h) => {
      const li = document.createElement("li");
      li.className = `chip chip-${h.kind}`;
      li.textContent = h.text;
      return li;
    }),
  );
  scoreButtons.forEach((b) => b.classList.toggle("low", Boolean(item.highlight_low) && Number(b.dataset.score) <= 4));
}

function adjust(type, sign) {
  if (type === "rate") progress.rated += sign;
  if (type === "not_seen") progress.not_seen += sign;
  if (type !== "later") progress.remaining -= sign;
  renderProgress();
}

function act(type, score) {
  const record = session.act(type, type === "rate" ? { score } : {});
  if (!record) return;
  render();
  adjust(type, +1);
  const body = { film_id: record.film_id, client_id: newId() };
  if (type === "rate") body.score = score;
  queue.enqueue({ type, body });
  if (session.needsRefill) session.refill(queue.size).then(render).catch(() => {});
}

async function undo() {
  const lastType = session.lastAction;
  const item = session.undo();
  if (item) {
    render();
    adjust(lastType, -1);
    queue.enqueue({ type: "undo", body: { client_id: newId() } });
    return;
  }
  // Nothing left locally: undo actions from an earlier visit directly on the server.
  await queue.idle();
  try {
    const data = await postJSON("/api/undo");
    if (data.item) session.unshift(data.item);
    setProgress(data.progress);
    render();
  } catch (error) {
    toast(error.status === 404 ? "Nichts zum Rückgängigmachen" : error.message);
  }
}

function handle(action) {
  if (action.type === "rate") act("rate", action.score);
  else if (action.type === "undo") undo();
  else act(action.type);
}

document.addEventListener("keydown", (event) => {
  const action = keyToAction(event);
  if (!action) return;
  event.preventDefault();
  if (event.repeat && action.type !== "undo") return;
  handle(action);
});

scoreButtons.forEach((button) =>
  button.addEventListener("click", () => handle({ type: "rate", score: Number(button.dataset.score) })),
);
document.querySelectorAll(".action-buttons .action").forEach((button) =>
  button.addEventListener("click", () => handle({ type: button.dataset.action })),
);

// When the page is hidden or closed, hand all unconfirmed actions to the browser in one ordered
// batch. Every action carries a client_id, so the server ignores ones it has already processed.
function flushWithBeacon() {
  const pending = queue.pending;
  if (!pending.length || !navigator.sendBeacon) return;
  const actions = pending.map((r) => ({ type: r.type, ...r.body }));
  navigator.sendBeacon("/api/actions", new Blob([JSON.stringify({ actions })], { type: "application/json" }));
}
window.addEventListener("pagehide", flushWithBeacon);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushWithBeacon();
});

session
  .start()
  .then(render)
  .catch((error) => toast(`Warteschlange konnte nicht geladen werden: ${error.message}`, "error"));
