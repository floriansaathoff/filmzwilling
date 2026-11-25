// One twin: all of their MovieLens ratings as a poster grid (paged), sheet with trailer and rating.
import { el, getJSON, postJSON, toast } from "./api.js";
import { openTrailer } from "./player.js";
import { openSheet } from "./sheet.js";
import { icon, setAmbient } from "./ui.js";

const app = document.getElementById("twin-app");
const rank = app.dataset.rank;
const controls = document.getElementById("twin-controls");
const grid = document.getElementById("twin-grid");
const more = document.getElementById("twin-more");
const count = document.getElementById("twin-count");
const items = new WeakMap();
let offset = 0;
const PAGE = 120;

function readUrl() {
  const params = new URLSearchParams(location.search);
  controls.elements.sort.value = params.get("sort") || "score";
  controls.elements.show.value = params.get("show") || "all";
}

function params() {
  const p = new URLSearchParams();
  if (controls.elements.sort.value !== "score") p.set("sort", controls.elements.sort.value);
  if (controls.elements.show.value !== "all") p.set("show", controls.elements.show.value);
  return p;
}

function tile(item) {
  const node = el("article", { class: "tile", tabindex: "0", "aria-label": `${item.title}, Zwilling ${item.their_score_text}`, dataset: { filmId: item.film_id } });
  const yours = el("span", { class: "tile-yours", hidden: item.your_score === null || item.your_score === undefined, text: `du ${item.your_score ?? ""}` });
  node.append(
    el("div", { class: "tile-art" },
      el("img", { class: "tile-poster", src: item.poster_url, alt: "", loading: "lazy" }),
      el("span", { class: "tile-match", title: "Note des Zwillings" }, item.their_score_text),
      yours,
      el("div", { class: "tile-overlay" },
        el("button", { type: "button", class: "btn-round", tabindex: "-1", title: "Trailer abspielen", "aria-label": `Trailer: ${item.title}`, onclick: (e) => { e.stopPropagation(); openTrailer(item); } }, icon("play")),
        el("button", { type: "button", class: "btn-round", tabindex: "-1", title: "Details", "aria-label": `Details: ${item.title}`, onclick: (e) => { e.stopPropagation(); open(item, yours); } }, icon("info")))),
    el("h3", { class: "tile-title", text: item.title, title: item.title }),
    el("p", { class: "tile-meta", text: [item.year, item.runtime ? `${item.runtime} Min.` : null].filter(Boolean).join(" · ") }),
  );
  node.addEventListener("click", () => open(item, yours));
  node.addEventListener("keydown", (e) => {
    if (e.target !== node) return;
    if (e.key === "Enter") open(item, yours);
    if (e.key === "t" || e.key === "T") openTrailer(item);
  });
  node.addEventListener("focus", () => setAmbient(item.poster_url));
  items.set(node, item);
  return node;
}

function open(item, yours) {
  openSheet({ ...item, reason: `Zwilling: ${item.their_score_text}${item.your_score !== null && item.your_score !== undefined ? ` · du: ${item.your_score}` : ""}` }, {
    onRate: async (score) => {
      try {
        await postJSON("/api/rate", { film_id: item.film_id, score, context: "twin" });
        item.your_score = score;
        yours.hidden = false;
        yours.textContent = `du ${score}`;
        toast(`„${item.title}“ mit ${score} bewertet`);
      } catch (error) {
        toast(error.message, "error");
      }
    },
  });
}

async function load({ append = false } = {}) {
  if (!append) offset = 0;
  const p = params();
  history.replaceState(null, "", p.toString() ? `?${p}` : location.pathname);
  p.set("offset", String(offset));
  p.set("limit", String(PAGE));
  try {
    const data = await getJSON(`/api/twins/${rank}?${p}`);
    const nodes = data.items.map(tile);
    if (append) grid.append(...nodes);
    else grid.replaceChildren(...nodes);
    offset += data.items.length;
    count.textContent = `${Math.min(offset, data.total)} von ${data.total} Filmen`;
    more.hidden = offset >= data.total;
    if (!append && data.items.length) setAmbient(data.items[0].poster_url);
    if (!data.total) grid.replaceChildren(el("p", { class: "muted", text: "Keine Filme in dieser Auswahl." }));
    return nodes;
  } catch (error) {
    toast(error.message, "error");
    return [];
  }
}

controls.addEventListener("change", () => load());
more.addEventListener("click", async () => {
  const nodes = await load({ append: true });
  if (nodes[0]) nodes[0].focus({ focusVisible: true });
});

// Controller: Y plays the trailer of the focused film, B goes back to all twins.
document.addEventListener("fz:pad", (event) => {
  const { button } = event.detail;
  const node = document.activeElement;
  if (button === "y" && node && items.has(node)) {
    event.preventDefault();
    openTrailer(items.get(node));
  } else if (button === "b" && !document.querySelector(".sheet-layer")) {
    event.preventDefault();
    location.href = "/zwillinge";
  }
});

readUrl();
load();
