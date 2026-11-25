// Rating page: Abyss spotlight, optimistic UI, keyboard and controller shortcuts, retry queue,
// poster/backdrop preloading and the trailer player.
import { el, formatNumber, getJSON, postJSON, toast } from "./api.js";
import { keyToAction } from "./keys.js";
import { isPlayerOpen, openTrailer } from "./player.js";
import { Preloader, RatingSession, RetryQueue } from "./queue.js";
import { fadeImage, icon, loadMedia, preloadImage, setAmbient } from "./ui.js";

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

function metaPill(name, text) {
  return el("span", { class: "meta-pill" }, name ? icon(name) : null, text);
}

const trailerBtn = $("trailer-btn");
const trailerText = trailerBtn.querySelector("span");
const backdropBox = $("spot-backdrop");

function showMedia(item, media) {
  if (session.current !== item) return;
  const backdrop = media && media.backdrop_url;
  backdropBox.classList.toggle("from-poster", !backdrop);
  fadeImage($("backdrop-img"), backdrop || item.poster_url);
  setAmbient(backdrop || item.poster_url);
  $("film-overview").textContent = (media && media.overview) || "";
  const count = media ? media.trailers.length : 0;
  trailerBtn.classList.toggle("unavailable", Boolean(media) && count === 0);
  trailerBtn.title = !media ? "" : count ? "Trailer abspielen (T / Y)" : media.online ? "Kein Trailer gefunden" : "Trailer brauchen TMDB";
  trailerText.textContent = media && count === 0 ? "Kein Trailer" : "Trailer";
}

function render() {
  const item = session.current;
  if (!item) {
    card.hidden = true;
    empty.hidden = false;
    $("rate-dock").hidden = true;
    return;
  }
  card.hidden = false;
  empty.hidden = true;
  $("rate-dock").hidden = false;
  const poster = $("poster");
  const cached = images.get(item.poster_url);
  poster.src = cached && cached.complete ? cached.src : item.poster_url;
  poster.alt = `Poster: ${item.title}`;
  $("film-title").textContent = item.title;
  $("film-original").textContent = item.original_title || "";
  const pills = [
    item.year ? metaPill("movie", String(item.year)) : null,
    item.runtime ? metaPill("clock", `${Math.floor(item.runtime / 60)}h ${item.runtime % 60}m`) : null,
    item.vote_average ? metaPill("star", formatNumber(item.vote_average)) : null,
    ...(item.genres || []).slice(0, 3).map((g) => metaPill(null, g)),
  ];
  $("film-meta").replaceChildren(...pills.filter(Boolean));
  const hints = $("film-hints");
  hints.replaceChildren(
    ...(item.hints || []).map((h) => {
      const li = document.createElement("li");
      li.className = `chip chip-${h.kind}`;
      li.textContent = h.text;
      return li;
    }),
  );
  const tmdb = $("tmdb-link");
  tmdb.hidden = !item.tmdb_url;
  if (item.tmdb_url) tmdb.href = item.tmdb_url;
  scoreButtons.forEach((b) => b.classList.toggle("low", Boolean(item.highlight_low) && Number(b.dataset.score) <= 4));
  showMedia(item, null);
  loadMedia(item.film_id).then((media) => showMedia(item, media));
  // Warm up backdrops of the next films so that switching stays instant.
  for (const next of session.upcoming.slice(0, 2)) {
    loadMedia(next.film_id).then((m) => preloadImage(m && m.backdrop_url));
  }
}

function pressFeedback(score) {
  const button = scoreButtons[score];
  if (!button) return;
  button.classList.remove("pressed");
  void button.offsetWidth;
  button.classList.add("pressed");
}

function adjust(type, sign) {
  if (type === "rate") progress.rated += sign;
  if (type === "not_seen") progress.not_seen += sign;
  if (type !== "later") progress.remaining -= sign;
  renderProgress();
}

function act(type, score) {
  if (type === "rate") pressFeedback(score);
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

function trailer() {
  const item = session.current;
  if (item) openTrailer(item);
}

function handle(action) {
  if (action.type === "trailer") trailer();
  else if (action.type === "rate") act("rate", action.score);
  else if (action.type === "undo") undo();
  else act(action.type);
}

document.addEventListener("keydown", (event) => {
  if (isPlayerOpen()) return;
  const action = keyToAction(event);
  if (!action) return;
  event.preventDefault();
  if (event.repeat && action.type !== "undo") return;
  handle(action);
});

trailerBtn.addEventListener("click", trailer);

// Controller: the D-pad moves over the score buttons (A rates via click), X/Y/B/RT are shortcuts.
const PAD_ACTIONS = { x: { type: "not_seen" }, y: { type: "trailer" }, b: { type: "undo" }, rt: { type: "later" } };
document.addEventListener("fz:pad", (event) => {
  const action = PAD_ACTIONS[event.detail.button];
  if (!action || card.hidden) return;
  event.preventDefault();
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
