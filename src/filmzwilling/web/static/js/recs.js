// Recommendations page: spotlight carousel of the top films, Abyss poster grid, film sheet,
// filters stored in the URL and the new-releases section.
import { el, formatNumber, getJSON, postJSON, toast } from "./api.js";
import { openTrailer } from "./player.js";
import { openSheet } from "./sheet.js";
import { fadeImage, icon, loadMedia, setAmbient } from "./ui.js";

const app = document.getElementById("recs-app");
const form = document.getElementById("filters");
const grid = document.getElementById("recs-grid");
const newGrid = document.getElementById("new-grid");
const countBox = document.getElementById("recs-count");
const defaults = (app.dataset.defaultProviders || "").split(",").filter(Boolean);

function readUrl() {
  const params = new URLSearchParams(location.search);
  const providers = params.has("providers") ? params.get("providers") : defaults.join(",");
  const anyBox = document.getElementById("providers-any");
  anyBox.checked = providers === "any" || (!params.has("providers") && defaults.length === 0);
  const chosen = new Set(providers.split(","));
  form.querySelectorAll('input[name="providers"]').forEach((box) => { box.checked = chosen.has(box.value); });
  const genres = new Set((params.get("genres") || "").split(",").filter(Boolean));
  form.querySelectorAll('input[name="genres"]').forEach((box) => { box.checked = genres.has(box.value); });
  form.elements.rent_buy.checked = params.get("rent_buy") === "1";
  form.elements.genre_mode.checked = params.get("genre_mode") === "and";
  for (const name of ["min_score", "min_support", "year_from", "year_to", "max_runtime"]) {
    form.elements[name].value = params.get(name) || "";
  }
  form.elements.sort.value = params.get("sort") || "match";
}

function currentParams() {
  const params = new URLSearchParams();
  if (document.getElementById("providers-any").checked) {
    params.set("providers", "any");
  } else {
    const ids = [...form.querySelectorAll('input[name="providers"]:checked')].map((b) => b.value);
    params.set("providers", ids.join(","));
  }
  const genres = [...form.querySelectorAll('input[name="genres"]:checked')].map((b) => b.value);
  if (genres.length) params.set("genres", genres.join(","));
  if (form.elements.genre_mode.checked) params.set("genre_mode", "and");
  if (form.elements.rent_buy.checked) params.set("rent_buy", "1");
  for (const name of ["min_score", "min_support", "year_from", "year_to", "max_runtime"]) {
    const value = form.elements[name].value.trim();
    if (value) params.set(name, value);
  }
  if (form.elements.sort.value !== "match") params.set("sort", form.elements.sort.value);
  return params;
}

function offersNode(item, showPaid) {
  const wanted = (item.offers || []).filter((o) => showPaid || !["rent", "buy"].includes(o.category));
  const seen = new Set();
  return el(
    "div",
    { class: "offers" },
    wanted
      .filter((o) => !seen.has(o.provider_id) && seen.add(o.provider_id))
      .slice(0, 4)
      .map((o) =>
        o.logo_url
          ? el("img", { src: o.logo_url, alt: o.name, title: `${o.name} (${o.category_label})`, loading: "lazy" })
          : el("span", { class: "offer-name", title: o.category_label, text: o.name }),
      ),
  );
}

const tileItems = new WeakMap();

function actionsFor(item, node) {
  return {
    onRate: (score) => rateItem(item, score, node),
    onHide: () => hideItem(item, node),
  };
}

function tile(item, { personalized }) {
  const node = el("article", {
    class: "tile",
    tabindex: "0",
    "aria-label": `${item.title}${item.year ? ` (${item.year})` : ""}`,
    dataset: { filmId: item.film_id },
  });
  const badge = personalized
    ? el("span", { class: "tile-match", title: item.support_text }, item.score_text)
    : el("span", { class: "tile-match", title: "TMDB-Note" }, item.vote_average ? formatNumber(item.vote_average) : "–", el("small", { text: "TMDB" }));
  const play = el("button", {
    type: "button", class: "btn-round", title: "Trailer abspielen", "aria-label": `Trailer: ${item.title}`, tabindex: "-1",
    onclick: (e) => { e.stopPropagation(); openTrailer(item); },
  }, icon("play"));
  const info = el("button", {
    type: "button", class: "btn-round", title: "Details", "aria-label": `Details: ${item.title}`, tabindex: "-1",
    onclick: (e) => { e.stopPropagation(); openSheet(item, actionsFor(item, node)); },
  }, icon("info"));
  node.append(
    el("div", { class: "tile-art" },
      el("img", { class: "tile-poster", src: item.poster_url, alt: "", loading: "lazy" }),
      badge,
      offersNode(item, form.elements.rent_buy.checked),
      el("div", { class: "tile-overlay" }, play, info)),
    el("h3", { class: "tile-title", text: item.title, title: item.title }),
    el("p", { class: "tile-meta", text: [item.year, item.runtime ? `${item.runtime} Min.` : null].filter(Boolean).join(" · ") }),
    personalized && item.reason ? el("p", { class: "tile-reason", text: item.reason }) : null,
  );
  node.addEventListener("click", () => openSheet(item, actionsFor(item, node)));
  node.addEventListener("keydown", (e) => {
    if (e.target !== node) return;
    if (e.key === "Enter") openSheet(item, actionsFor(item, node));
    if (e.key === "t" || e.key === "T") openTrailer(item);
  });
  node.addEventListener("focus", () => setAmbient(item.poster_url));
  return node;
}

// Controller on a focused tile: Y plays the trailer, X marks "not interested".
document.addEventListener("fz:pad", (event) => {
  const node = document.activeElement;
  if (!node || !node.classList || !node.classList.contains("tile")) return;
  const item = tileItems.get(node);
  if (!item) return;
  if (event.detail.button === "y") {
    event.preventDefault();
    openTrailer(item);
  }
});

function tiles(items, opts) {
  return items.map((item) => {
    const node = tile(item, opts);
    tileItems.set(node, item);
    return node;
  });
}

// --- spotlight carousel (top 5) ---
const hero = document.getElementById("spotlight");
const heroContent = document.getElementById("hero-content");
const heroBackdrop = document.getElementById("hero-backdrop");
const heroDots = document.getElementById("hero-dots");
let heroItems = [];
let heroIndex = 0;
let heroTimer = null;

function showHero(index) {
  if (!heroItems.length) return;
  heroIndex = (index + heroItems.length) % heroItems.length;
  const item = heroItems[heroIndex];
  const backdropBox = heroBackdrop.parentElement;
  backdropBox.classList.add("from-poster");
  fadeImage(heroBackdrop, item.poster_url);
  setAmbient(item.poster_url);
  const plot = el("p", { class: "spot-plot" });
  const trailerBtn = el("button", { type: "button", class: "btn-play", onclick: () => openTrailer(item) }, icon("play"), el("span", { text: "Trailer" }));
  const node = grid.querySelector(`[data-film-id="${item.film_id}"]`);
  heroContent.replaceChildren(
    el("div", { class: "match-big" }, el("strong", { text: item.score_text }), el("span", { text: `Match · ${item.support_text}` })),
    el("h2", { class: "spot-title", text: item.title }),
    el("div", { class: "meta-pills" },
      item.year ? el("span", { class: "meta-pill" }, icon("movie"), String(item.year)) : null,
      item.runtime ? el("span", { class: "meta-pill" }, icon("clock"), `${Math.floor(item.runtime / 60)}h ${item.runtime % 60}m`) : null,
      item.vote_average ? el("span", { class: "meta-pill" }, icon("star"), formatNumber(item.vote_average)) : null,
      ...(item.genres || []).slice(0, 3).map((g) => el("span", { class: "meta-pill", text: g }))),
    plot,
    item.reason ? el("p", { class: "reason", text: item.reason }) : null,
    el("div", { class: "spot-buttons" },
      trailerBtn,
      el("button", { type: "button", class: "btn-round", title: "Details und bewerten", "aria-label": "Details und bewerten", onclick: () => openSheet(item, actionsFor(item, node || el("div"))) }, icon("info"))),
  );
  [...heroDots.children].forEach((d, i) => {
    d.classList.toggle("active", i === heroIndex);
    d.setAttribute("aria-selected", String(i === heroIndex));
  });
  loadMedia(item.film_id).then((media) => {
    if (heroItems[heroIndex] !== item || !media) return;
    if (media.backdrop_url) {
      backdropBox.classList.remove("from-poster");
      fadeImage(heroBackdrop, media.backdrop_url);
      setAmbient(media.backdrop_url);
    }
    plot.textContent = media.overview || "";
    if (!media.trailers.length) {
      trailerBtn.classList.add("unavailable");
      trailerBtn.lastChild.textContent = "Kein Trailer";
    }
  });
  restartHeroTimer();
}

function restartHeroTimer() {
  clearInterval(heroTimer);
  heroTimer = setInterval(() => {
    if (!hero.matches(":hover") && !hero.contains(document.activeElement) && !document.querySelector(".player, .sheet-layer")) showHero(heroIndex + 1);
  }, 9000);
}

function setHero(items) {
  heroItems = items.slice(0, 5);
  hero.hidden = heroItems.length === 0;
  heroDots.replaceChildren(
    ...(heroItems.length > 1
      ? heroItems.map((item, i) => el("button", { type: "button", class: "dot", role: "tab", tabindex: "-1", "aria-label": item.title, onclick: () => showHero(i) }))
      : []),
  );
  if (heroItems.length) showHero(0);
  else clearInterval(heroTimer);
}

async function rateItem(item, score, node) {
  node.remove();
  try {
    await postJSON("/api/rate", { film_id: item.film_id, score, context: "recommendations" });
    toast(`„${item.title}“ mit ${score} bewertet`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function hideItem(item, node) {
  node.remove();
  try {
    await postJSON("/api/not-interested", { film_id: item.film_id });
    toast(`„${item.title}“ ausgeblendet`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function load() {
  const params = currentParams();
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
  try {
    const data = await getJSON(`/api/recommendations?${query}`);
    if (data.status !== "ok") {
      grid.replaceChildren(el("p", { class: "notice", text: data.message }));
      countBox.textContent = "";
      setHero([]);
    } else {
      grid.replaceChildren(...tiles(data.items, { personalized: true }));
      setHero(data.items);
      countBox.textContent = data.total > data.items.length
        ? `${data.items.length} von ${data.total} passenden Filmen`
        : `${data.total} passende Filme`;
      if (!data.items.length) grid.append(el("p", { class: "muted", text: "Keine Treffer mit diesen Filtern." }));
    }
    const fresh = await getJSON(`/api/new-releases?${query}`);
    newGrid.replaceChildren(...tiles(fresh.items, { personalized: false }));
    if (!fresh.items.length) newGrid.append(el("p", { class: "muted", text: "Noch keine Neuerscheinungen geladen oder keine passenden." }));
  } catch (error) {
    toast(error.message, "error");
  }
}

let timer = null;
form.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 250); });
form.addEventListener("submit", (event) => { event.preventDefault(); load(); });

async function button(id, url, message) {
  const node = document.getElementById(id);
  node.addEventListener("click", async () => {
    node.disabled = true;
    try {
      await postJSON(url);
      toast(message);
      await load();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      node.disabled = false;
    }
  });
}
button("recompute", "/api/recompute", "Empfehlungen neu berechnet");
button("refresh-availability", "/api/availability/refresh", "Verfügbarkeit aktualisiert");
button("refresh-new", "/api/new-releases/refresh", "Neuerscheinungen geladen");

const toggle = document.getElementById("toggle-filters");
function showFilters(open) {
  form.hidden = !open;
  toggle.setAttribute("aria-expanded", String(open));
  sessionStorage.setItem("fz-filters-open", open ? "1" : "0");
}
toggle.addEventListener("click", () => showFilters(form.hidden));
showFilters(sessionStorage.getItem("fz-filters-open") === "1");

readUrl();
load();
