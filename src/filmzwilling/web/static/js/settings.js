// Settings: own profiles, own providers, excluded genres, queue size (saved right away), self-test, recomputation
// and the entry to the data-science page. Controller friendly: chips, big -/+ steppers, no
// dropdowns.
import { el, formatNumber, getJSON, postJSON, putJSON, toast } from "./api.js";
import { stepNumber } from "./pad.js";

const form = document.getElementById("settings-form");
const status = document.getElementById("settings-status");
const queueInput = document.getElementById("queue-size");

function chip(name, value, label, checked, logo) {
  return el("label", { class: "chip-toggle" },
    el("input", { type: "checkbox", name, value, checked }),
    el("span", { class: "chip-face" }, logo ? el("img", { src: logo, alt: "", loading: "lazy" }) : null, label));
}

async function load() {
  const data = await getJSON("/api/settings");
  document.getElementById("profiles").replaceChildren(
    ...(data.all_profiles.length
      ? data.all_profiles.map((p) => chip("profiles", p, p, data.my_profiles.includes(p)))
      : [el("p", { class: "muted", text: "Noch keine Sehverläufe importiert." })]),
  );
  const mine = new Set(data.my_providers);
  document.getElementById("providers").replaceChildren(
    ...(data.providers.length
      ? data.providers.map((p) => chip("providers", p.id, p.name, mine.has(p.id), p.logo_url))
      : [el("p", { class: "muted", text: "Noch keine Anbieterliste (mit 'filmzwilling tmdb-sync' laden)." })]),
  );
  const excluded = new Set(data.excluded_genres);
  document.getElementById("excluded-genres").replaceChildren(
    ...(data.all_genres.length
      ? data.all_genres.map((g) => chip("excluded_genres", g, g, excluded.has(g)))
      : [el("p", { class: "muted", text: "Noch keine Filme mit Genres (zuerst 'filmzwilling setup')." })]),
  );
  queueInput.value = data.queue_size;
}

let saveTimer = null;
let saving = Promise.resolve();
function setStatus(text, kind = "") {
  status.textContent = text;
  status.dataset.kind = kind;
}

async function save() {
  const body = {
    my_profiles: [...form.querySelectorAll('input[name="profiles"]:checked')].map((b) => b.value),
    queue_size: Math.max(0, Math.min(100000, Math.round(Number(queueInput.value || 0)))),
  };
  const providerBoxes = [...form.querySelectorAll('input[name="providers"]')];
  const genreBoxes = [...form.querySelectorAll('input[name="excluded_genres"]')];
  if (genreBoxes.length) body.excluded_genres = genreBoxes.filter((b) => b.checked).map((b) => b.value);
  if (providerBoxes.length) body.my_providers = providerBoxes.filter((b) => b.checked).map((b) => Number(b.value));
  setStatus("Speichert …");
  try {
    await putJSON("/api/settings", body);
    setStatus("Gespeichert", "ok");
  } catch (error) {
    setStatus(error.message, "error");
    toast(error.message, "error");
  }
}

function scheduleSave(delay = 450) {
  clearTimeout(saveTimer);
  setStatus("Änderung …");
  saveTimer = setTimeout(() => { saving = saving.then(save); }, delay);
}

form.addEventListener("change", () => scheduleSave(150));
queueInput.addEventListener("input", () => scheduleSave());

const stepper = form.querySelector(".queue-stepper");
const stepOpts = { step: Number(stepper.dataset.step), start: Number(stepper.dataset.start), min: Number(stepper.dataset.min), max: Number(stepper.dataset.max) };
stepper.querySelectorAll(".step-btn").forEach((button) =>
  button.addEventListener("click", () => {
    const next = stepNumber(queueInput.value, Number(button.dataset.dir), stepOpts);
    queueInput.value = next === "" ? "0" : next;
    scheduleSave();
  }));

// Flush a pending save before leaving the page.
window.addEventListener("pagehide", () => {
  if (saveTimer && status.textContent.startsWith("Änderung")) {
    clearTimeout(saveTimer);
    save();
  }
});

function evalTile(label, value, sub) {
  return el("div", { class: "eval-tile" }, el("span", { class: "muted", text: label }), el("strong", { text: value }), el("span", { class: "muted", text: sub }));
}

document.getElementById("run-evaluate").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.querySelector("span").textContent = "Selbsttest läuft …";
  try {
    const r = await postJSON("/api/evaluate");
    document.getElementById("evaluation").replaceChildren(
      evalTile("RMSE", formatNumber(r.rmse, 2), `Filmdurchschnitt ${formatNumber(r.baseline_rmse, 2)}`),
      evalTile("Spearman", formatNumber(r.spearman, 2), `Filmdurchschnitt ${formatNumber(r.baseline_spearman, 2)}`),
      el("p", { class: "muted eval-note", text: `5-fache Kreuzvalidierung über ${r.n_ratings} eigene Bewertungen.` }),
    );
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Selbsttest starten";
    button.focus({ preventScroll: true });
  }
});

document.getElementById("recompute").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.querySelector("span").textContent = "Berechne …";
  try {
    const r = await postJSON("/api/recompute");
    document.getElementById("recs-info").textContent =
      `Gerade berechnet: ${r.count} Empfehlungen aus ${r.rating_count} Bewertungen in ${formatNumber(r.duration, 1)} s.`;
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Empfehlungen neu berechnen";
    button.focus({ preventScroll: true });
  }
});

// Decorative point cloud on the data-science entry (deterministic, three clusters + you).
function drawEntryArt() {
  const svg = document.getElementById("ds-entry-art");
  if (!svg) return;
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const gauss = () => Math.sqrt(-2 * Math.log(rnd() + 1e-9)) * Math.cos(2 * Math.PI * rnd());
  const centers = [[110, 70, "c1"], [205, 60, "c2"], [170, 112, "c3"]];
  const NS = "http://www.w3.org/2000/svg";
  for (let i = 0; i < 150; i++) {
    const [cx, cy, cls] = centers[i % 3];
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", (cx + gauss() * 26).toFixed(1));
    c.setAttribute("cy", (cy + gauss() * 15).toFixed(1));
    c.setAttribute("r", (1 + rnd() * 1.8).toFixed(2));
    c.setAttribute("class", cls);
    c.style.animationDelay = `${(rnd() * 4).toFixed(2)}s`;
    svg.append(c);
  }
  const you = document.createElementNS(NS, "circle");
  Object.entries({ cx: 118, cy: 72, r: 5, class: "you" }).forEach(([k, v]) => you.setAttribute(k, v));
  svg.append(you);
}

drawEntryArt();
load().catch((error) => toast(error.message, "error"));
