// Film detail sheet (Abyss glass dialog): backdrop, plot, trailer, rate 0-10, not interested.
import { el, formatNumber } from "./api.js";
import { openTrailer } from "./player.js";
import { play, rate as rateSound } from "./sfx.js";
import { fadeImage, icon, loadMedia } from "./ui.js";

let layer = null;
let opener = null;

export function closeSheet({ silent = false } = {}) {
  if (!layer) return;
  layer.remove();
  layer = null;
  if (!silent) play("close");
  for (const node of document.querySelectorAll("[data-sheet-inert]")) {
    node.inert = false;
    delete node.dataset.sheetInert;
  }
  if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
  opener = null;
}

/**
 * @param item recommendation or new-release item (film_id, title, year, runtime, genres, …)
 * @param actions {onRate(score), onHide()}
 */
export function openSheet(item, { onRate, onHide } = {}) {
  closeSheet({ silent: true });
  play("open");
  opener = document.activeElement;
  const backdrop = el("img", { alt: "" });
  const plot = el("p", { class: "spot-plot" });
  const trailerBtn = el("button", { type: "button", class: "btn-play", onclick: () => openTrailer(item) }, icon("play"), el("span", { text: "Trailer" }));
  const pills = [
    item.score_text ? el("span", { class: "meta-pill" }, icon("twins"), `Match ${item.score_text}`) : null,
    item.year ? el("span", { class: "meta-pill" }, icon("movie"), String(item.year)) : null,
    item.runtime ? el("span", { class: "meta-pill" }, icon("clock"), `${Math.floor(item.runtime / 60)}h ${item.runtime % 60}m`) : null,
    item.vote_average ? el("span", { class: "meta-pill" }, icon("star"), formatNumber(item.vote_average)) : null,
    ...(item.genres || []).slice(0, 3).map((g) => el("span", { class: "meta-pill", text: g })),
  ];
  const close = el("button", { type: "button", class: "btn-round sheet-close", title: "Schließen", "aria-label": "Schließen", onclick: closeSheet }, icon("close"));
  const sheet = el(
    "div",
    { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": item.title },
    close,
    el("div", { class: "spotlight" },
      el("div", { class: "spot-backdrop from-poster" }, backdrop),
      el("div", { class: "spot-content" },
        el("h2", { class: "spot-title", text: item.title }),
        el("div", { class: "meta-pills" }, pills.filter(Boolean)),
        item.reason ? el("p", { class: "muted", text: item.reason }) : null,
        plot,
        el("div", { class: "spot-buttons" },
          trailerBtn,
          item.tmdb_url ? el("a", { class: "btn-round", href: item.tmdb_url, target: "_blank", rel: "noopener", title: "Auf TMDB öffnen", "aria-label": "Auf TMDB öffnen" }, icon("info")) : null))),
    el("div", { class: "sheet-body" },
      onRate
        ? [el("h3", { text: "Schon gesehen? Bewerten:" }),
          el("div", { class: "sheet-rate", role: "group", "aria-label": "Note" },
            Array.from({ length: 11 }, (_, n) => el("button", { type: "button", text: String(n), onclick: () => { closeSheet({ silent: true }); rateSound(n); onRate(n); } })))]
        : null,
      el("div", { class: "sheet-actions" },
        onHide ? el("button", { type: "button", class: "secondary", onclick: () => { closeSheet(); onHide(); } }, icon("block"), "Kein Interesse") : null,
        el("button", { type: "button", class: "secondary", text: "Schließen", onclick: closeSheet }))),
  );
  layer = el("div", { class: "sheet-layer", onclick: (e) => { if (e.target === layer) closeSheet(); } }, sheet);
  for (const node of document.body.children) {
    if (!node.inert && node.tagName !== "SCRIPT") {
      node.inert = true;
      node.dataset.sheetInert = "1";
    }
  }
  document.body.append(layer);
  fadeImage(backdrop, item.poster_url);
  trailerBtn.focus({ preventScroll: true });
  loadMedia(item.film_id).then((media) => {
    if (!layer || !media) return;
    if (media.backdrop_url) {
      backdrop.parentElement.classList.remove("from-poster");
      fadeImage(backdrop, media.backdrop_url);
    }
    plot.textContent = media.overview || "";
    if (!media.trailers.length) {
      trailerBtn.classList.add("unavailable");
      trailerBtn.lastChild.textContent = "Kein Trailer";
    }
  });
}

document.addEventListener("keydown", (event) => {
  if (layer && event.key === "Escape" && !document.querySelector(".player")) closeSheet();
});
