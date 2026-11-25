// Shared UI pieces for the Abyss design: icons, ambient background, film media (backdrop, plot,
// trailers) with a small cache.
import { getJSON } from "./api.js";

const SVG = "http://www.w3.org/2000/svg";

/** <svg class="i"><use href="/static/icons.svg#name"></svg> */
export function icon(name, cls = "") {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", `i ${cls}`.trim());
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const use = document.createElementNS(SVG, "use");
  use.setAttribute("href", `/static/icons.svg#${name}`);
  svg.append(use);
  return svg;
}

/** Swap an <svg class="i"> icon in place. */
export function setIcon(svg, name) {
  const use = svg && svg.querySelector("use");
  if (use) use.setAttribute("href", `/static/icons.svg#${name}`);
}

/** Fade an <img> to a new source once it has loaded (no flash of an empty image). */
export function fadeImage(img, url) {
  if (!img) return;
  if (!url) {
    img.classList.remove("loaded");
    img.removeAttribute("src");
    return;
  }
  if (img.dataset.url === url) return;
  img.dataset.url = url;
  const probe = new Image();
  probe.decoding = "async";
  probe.onload = () => {
    if (img.dataset.url !== url) return;
    img.classList.remove("loaded");
    img.src = url;
    requestAnimationFrame(() => img.classList.add("loaded"));
  };
  probe.onerror = () => { if (img.dataset.url === url) img.classList.remove("loaded"); };
  probe.src = url;
}

/** The blurred full-page background behind everything. */
export function setAmbient(url) {
  fadeImage(document.getElementById("ambient-img"), url);
}

const mediaCache = new Map();

/** GET /api/films/{id}/media once per film; failures resolve to null (never break the page). */
export function loadMedia(filmId) {
  if (filmId === undefined || filmId === null) return Promise.resolve(null);
  if (!mediaCache.has(filmId)) {
    const promise = getJSON(`/api/films/${filmId}/media`).catch(() => {
      mediaCache.delete(filmId);
      return null;
    });
    mediaCache.set(filmId, promise);
  }
  return mediaCache.get(filmId);
}

export function preloadImage(url) {
  if (!url) return;
  const img = new Image();
  img.decoding = "async";
  img.src = url;
}
