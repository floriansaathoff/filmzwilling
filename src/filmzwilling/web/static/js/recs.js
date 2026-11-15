// Recommendations page: filters stored in the URL, tiles, actions and the new-releases section.
import { el, formatNumber, getJSON, postJSON, toast } from "./api.js";

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
  const wanted = item.offers.filter((o) => showPaid || !["rent", "buy"].includes(o.category));
  const seen = new Set();
  return el(
    "div",
    { class: "offers" },
    wanted
      .filter((o) => !seen.has(o.provider_id) && seen.add(o.provider_id))
      .map((o) =>
        o.logo_url
          ? el("img", { src: o.logo_url, alt: o.name, title: `${o.name} (${o.category_label})`, loading: "lazy" })
          : el("span", { class: "offer-name", title: o.category_label, text: o.name }),
      ),
  );
}

function tile(item, { personalized }) {
  const rateBox = el("div", { class: "tile-rate", hidden: true },
    ...Array.from({ length: 11 }, (_, n) =>
      el("button", { type: "button", class: "mini-score", text: String(n), onclick: () => rateItem(item, n, node) })),
  );
  const node = el(
    "article",
    { class: "tile", dataset: { filmId: item.film_id } },
    el("img", { class: "tile-poster", src: item.poster_url, alt: "", loading: "lazy" }),
    el(
      "div",
      { class: "tile-body" },
      personalized
        ? el("div", { class: "match" }, el("span", { class: "match-value", text: item.score_text }),
            el("span", { class: "match-support", text: item.support_text }))
        : el("div", { class: "match tmdb" }, el("span", { class: "match-value", text: item.vote_average ? formatNumber(item.vote_average) : "–" }),
            el("span", { class: "match-support", text: "TMDB-Note" })),
      el("h3", { class: "tile-title", text: item.title }),
      el("p", { class: "tile-meta", text: [item.year, item.runtime ? `${item.runtime} Min.` : null].filter(Boolean).join(" · ") }),
      el("p", { class: "tile-genres", text: (item.genres || []).join(", ") }),
      personalized ? el("p", { class: "tile-reason muted", text: item.reason }) : null,
      offersNode(item, form.elements.rent_buy.checked),
      el(
        "div",
        { class: "tile-actions" },
        el("button", { type: "button", class: "secondary small", text: "Schon gesehen, bewerten", onclick: () => { rateBox.hidden = !rateBox.hidden; } }),
        el("button", { type: "button", class: "secondary small", text: "Kein Interesse", onclick: () => hideItem(item, node) }),
        item.tmdb_url ? el("a", { class: "small", href: item.tmdb_url, target: "_blank", rel: "noopener", text: "TMDB" }) : null,
      ),
      rateBox,
    ),
  );
  return node;
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
    } else {
      grid.replaceChildren(...data.items.map((item) => tile(item, { personalized: true })));
      countBox.textContent = data.total > data.items.length
        ? `${data.items.length} von ${data.total} passenden Filmen`
        : `${data.total} passende Filme`;
      if (!data.items.length) grid.append(el("p", { class: "muted", text: "Keine Treffer mit diesen Filtern." }));
    }
    const fresh = await getJSON(`/api/new-releases?${query}`);
    newGrid.replaceChildren(...fresh.items.map((item) => tile(item, { personalized: false })));
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

readUrl();
load();
