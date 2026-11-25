// Controller support (Gamepad API) on every page: spatial focus navigation with D-pad or left
// stick, A to activate, B to go back, shoulder buttons to switch pages, right stick to scroll.
// Pages can take over buttons by listening for the cancelable "fz:pad" event on document.
import { el, toast } from "./api.js";
import { newlyPressed, PadReader, pickNeighbor, scrollVector } from "./pad.js";
import { handlePad as playerPad, isPlayerOpen } from "./player.js";
import { play } from "./sfx.js";
import { icon } from "./ui.js";

const FOCUSABLE = ['a[href]', "button:not([disabled])", 'input:not([disabled]):not([type="hidden"])', "select:not([disabled])", "summary", '[tabindex="0"]']
  .map((s) => `${s}:not([tabindex="-1"])`).join(", ");
const REMAP_KEY = "fz-pad-remap";
let reader = new PadReader();
let readerFor = null;
let running = false;
let helpLayer = null;
let announced = false;
let learner = null;
let lastRect = null;
let lastRepeat = false;

function loadRemap(id) {
  try {
    return JSON.parse(localStorage.getItem(REMAP_KEY) || "{}")[id] || null;
  } catch {
    return null;
  }
}

function saveRemap(id, remap) {
  let all = {};
  try { all = JSON.parse(localStorage.getItem(REMAP_KEY) || "{}"); } catch { all = {}; }
  if (remap) all[id] = remap;
  else delete all[id];
  localStorage.setItem(REMAP_KEY, JSON.stringify(all));
}

function readerForPad(pad) {
  if (readerFor !== pad.id) {
    readerFor = pad.id;
    reader = new PadReader({ remap: loadRemap(pad.id) });
  }
  return reader;
}

let analog = null;

/**
 * Let a page use the sticks as analog input (e.g. to rotate a 3D view). The handler gets the
 * pad and the frame time in ms and returns true while it uses the sticks; the left stick then
 * no longer moves the focus and the right stick no longer scrolls. Pass null to stop.
 */
export function setAnalogHandler(handler) {
  analog = handler;
}

function visible(node) {
  if (node.closest("[inert], [hidden]")) return false;
  const rects = node.getClientRects();
  if (!rects.length) return false;
  const style = getComputedStyle(node);
  return style.visibility !== "hidden" && style.display !== "none";
}

function scopeRoot() {
  return helpLayer || document.querySelector(".sheet-layer") || document;
}

function focusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter(visible);
}

function rectOf(node) {
  const r = node.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}

function focusNode(node) {
  document.querySelectorAll(".pad-focus").forEach((n) => n.classList.remove("pad-focus"));
  node.classList.add("pad-focus");
  node.focus({ preventScroll: true, focusVisible: true });
  const r = node.getBoundingClientRect();
  const margin = 90;
  if (r.top < margin || r.bottom > innerHeight - margin || r.left < 0 || r.right > innerWidth) {
    // While a direction is held, smooth scrolling lags behind and the next pick uses stale rects.
    node.scrollIntoView({ block: "center", inline: "nearest", behavior: lastRepeat ? "auto" : "smooth" });
  }
  lastRect = rectOf(node);
}

function defaultTarget(root) {
  const preferred = [...root.querySelectorAll("[data-pad-default]")].find(visible);
  if (preferred) return preferred;
  const inMain = root === document ? focusables(document.querySelector("main") || document) : [];
  return inMain[0] || focusables(root)[0] || null;
}

function move(dir) {
  const root = scopeRoot();
  const items = focusables(root);
  const current = document.activeElement;
  if (!current || current === document.body || !items.includes(current)) {
    // Focus got lost (list reloaded, element removed): continue next to where it was.
    const nearest = lastRect && root === document ? nearestTo(lastRect, items) : null;
    const start = nearest || defaultTarget(root);
    if (start) {
      focusNode(start);
      play("move");
    }
    return;
  }
  const others = items.filter((n) => n !== current);
  const index = pickNeighbor(rectOf(current), others.map(rectOf), dir);
  if (index >= 0) {
    focusNode(others[index]);
    play("move");
  } else if (dir === "up" || dir === "down") {
    const scroller = root === document ? window : root.querySelector(".sheet") || window;
    scroller.scrollBy({ top: (dir === "down" ? 1 : -1) * innerHeight * 0.4, behavior: "smooth" });
  }
}

function nearestTo(rect, items) {
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h / 2;
  let best = null;
  let bestDist = Infinity;
  for (const node of items) {
    const r = rectOf(node);
    const d = Math.hypot(r.x + r.w / 2 - cx, r.y + r.h / 2 - cy);
    if (d < bestDist) {
      best = node;
      bestDist = d;
    }
  }
  return bestDist < innerHeight ? best : null;
}

function activate() {
  const node = document.activeElement;
  if (!node || node === document.body) {
    move("down");
    return;
  }
  if (node.tagName === "INPUT" && !["checkbox", "radio", "button", "submit"].includes(node.type)) {
    node.select && node.select();
    return;
  }
  play("select");
  node.click();
}

function switchPage(step) {
  const tabs = [...document.querySelectorAll(".tabs .tab")];
  if (!tabs.length) return;
  const current = tabs.findIndex((t) => t.classList.contains("active"));
  const next = tabs[(current + step + tabs.length) % tabs.length];
  play("page");
  location.href = next.href;
}

function back() {
  const close = document.querySelector(".sheet-layer .sheet-close");
  if (close) {
    close.click();
    return;
  }
  const filters = document.getElementById("toggle-filters");
  if (filters && filters.getAttribute("aria-expanded") === "true") {
    filters.click();
    focusNode(filters);
    return;
  }
  if (document.activeElement && document.activeElement !== document.body) {
    play("back");
    document.activeElement.blur();
    document.querySelectorAll(".pad-focus").forEach((n) => n.classList.remove("pad-focus"));
  }
}

const HELP = [
  ["Steuerkreuz / linker Stick", "Auswahl bewegen"],
  ["A", "Auswählen, bewerten"],
  ["B", "Zurück, schließen (beim Bewerten: rückgängig)"],
  ["X", "Nicht gesehen (Bewerten)"],
  ["Y", "Trailer abspielen"],
  ["RT", "Später (Bewerten)"],
  ["LB / RB", "Vorherige / nächste Seite"],
  ["Start", "Filter öffnen/schließen; X setzt sie zurück"],
  ["Rechter Stick", "Scrollen"],
  ["Data Science", "Linker Stick drehen · rechter Stick zoomen · ←/→ nächster Punkt · ↑/↓ Gruppe · A Details · LT/RT Genre · Y Autodrehung · X Ansicht zurücksetzen · LB/RB Ansicht · Start Vollbild"],
  ["Im Trailer", "A Pause · ←/→ 10 s · LT/RT 30 s · ↑/↓ Lautstärke · X Ton · Y Vollbild · LB/RB Trailer wechseln · B schließen"],
  ["Select / View", "Diese Hilfe"],
];

function toggleHelp() {
  if (helpLayer) {
    helpLayer.remove();
    helpLayer = null;
    learner = null;
    play("close");
    return;
  }
  play("open");
  const close = el("button", { type: "button", class: "secondary", text: "Schließen", onclick: () => toggleHelp() });
  const pad = firstPad();
  const learn = el("button", { type: "button", class: "secondary", onclick: () => startLearning() }, icon("tune"), "Tasten anlernen");
  const reset = el("button", { type: "button", class: "secondary", hidden: !(pad && loadRemap(pad.id)), onclick: () => {
    if (!pad) return;
    saveRemap(pad.id, null);
    readerFor = null;
    reset.hidden = true;
    toast("Standardbelegung wiederhergestellt");
  } }, icon("refresh"), "Standardbelegung");
  helpLayer = el("div", { class: "pad-help", role: "dialog", "aria-modal": "true", "aria-label": "Controller-Hilfe", onclick: (e) => { if (e.target === helpLayer) toggleHelp(); } },
    el("div", { class: "glass-panel" },
      el("h2", {}, icon("gamepad"), "Controller"),
      el("dl", {}, HELP.flatMap(([keys, text]) => [el("dt", {}, ...keys.split(" / ").flatMap((k, i) => [i ? " / " : null, k.length <= 7 ? el("kbd", { text: k }) : k])), el("dd", { text })])),
      el("p", { class: "pad-learn", id: "pad-learn", hidden: true }),
      el("div", { class: "pad-help-actions" }, close, learn, reset)));
  document.body.append(helpLayer);
  focusNode(close);
}

// Pads without the standard mapping ("HID-konformer Gamecontroller") number their buttons
// differently. The wizard asks for each button once and stores {name: index} per pad id.
const LEARN = [
  ["a", "A (Auswählen)"], ["b", "B (Zurück)"], ["x", "X"], ["y", "Y"],
  ["lb", "LB (linke Schultertaste)"], ["rb", "RB (rechte Schultertaste)"],
  ["lt", "LT (linker Trigger)"], ["rt", "RT (rechter Trigger)"],
  ["select", "Select / View"], ["start", "Start / Menu"],
];

// Some browsers (Firefox) update Gamepad objects in place, so keep a copy of the last state.
const snapshot = (pad) => ({ buttons: [...pad.buttons].map((b) => ({ pressed: b.pressed, value: b.value })) });

function startLearning() {
  const pad = firstPad();
  if (!pad) return;
  learner = { step: 0, map: {}, before: snapshot(pad), id: pad.id, started: performance.now() };
  showLearnStep();
}

function showLearnStep() {
  const box = document.getElementById("pad-learn");
  if (!box || !learner) return;
  box.hidden = false;
  box.replaceChildren(el("strong", { text: `Drück jetzt: ${LEARN[learner.step][1]}` }),
    el("span", { text: ` (${learner.step + 1}/${LEARN.length}, Steuerkreuz wird automatisch erkannt)` }));
}

function learnFrame(pad) {
  // Ignore what is still held from pressing "Tasten anlernen".
  const fresh = performance.now() - learner.started > 300 ? newlyPressed(learner.before, pad) : [];
  learner.before = snapshot(pad);
  const index = fresh.find((i) => !Object.values(learner.map).includes(i));
  if (index === undefined) return;
  learner.map[LEARN[learner.step][0]] = index;
  play("toggle");
  learner.step += 1;
  if (learner.step < LEARN.length) {
    showLearnStep();
    return;
  }
  // Standard D-pad buttons only if the pad actually has them and they were not reused.
  const used = Object.values(learner.map);
  if (pad.mapping === "standard" || pad.buttons.length > 15) {
    ["up", "down", "left", "right"].forEach((name, i) => { if (!used.includes(12 + i) && pad.buttons.length > 12 + i) learner.map[name] = 12 + i; });
  }
  saveRemap(learner.id, learner.map);
  readerFor = null;
  learner = null;
  const box = document.getElementById("pad-learn");
  if (box) box.replaceChildren(el("strong", { text: "Gespeichert. Die neue Belegung gilt ab sofort." }));
  play("connect");
}

function route(button) {
  document.body.classList.add("pad-mode");
  if (helpLayer) {
    if (["b", "select", "start"].includes(button)) toggleHelp();
    else if (button === "a") activate();
    else if (["up", "down", "left", "right"].includes(button)) move(button);
    return;
  }
  if (isPlayerOpen()) {
    if (playerPad(button)) return;
    if (button === "b") return;
  }
  if (button === "select") {
    toggleHelp();
    return;
  }
  const event = new CustomEvent("fz:pad", { detail: { button }, cancelable: true });
  if (!document.dispatchEvent(event)) return;
  if (["up", "down", "left", "right"].includes(button)) move(button);
  else if (button === "a") activate();
  else if (button === "b") back();
  else if (button === "lb") switchPage(-1);
  else if (button === "rb") switchPage(1);
}

function firstPad() {
  const pads = navigator.getGamepads ? [...navigator.getGamepads()] : [];
  return pads.find((p) => p && p.connected) || null;
}

function loop(now) {
  const pad = firstPad();
  if (!pad) {
    running = false;
    return;
  }
  const dt = Math.min(64, now - (loop.last || now));
  loop.last = now;
  const sticks = Boolean(analog && !learner && !helpLayer && !isPlayerOpen() && !document.querySelector(".sheet-layer") && analog(pad, dt));
  if (learner) {
    learnFrame(pad);
  } else {
    for (const { button, repeat } of readerForPad(pad).read(sticks ? { buttons: pad.buttons, axes: [] } : pad, now)) {
      lastRepeat = repeat;
      route(button);
    }
  }
  const [dx, dy] = sticks ? [0, 0] : scrollVector(pad);
  if ((dx || dy) && !isPlayerOpen()) {
    const sheet = document.querySelector(".sheet-layer .sheet");
    (sheet || window).scrollBy(dx, dy);
  }
  requestAnimationFrame(loop);
}

function start() {
  const indicator = document.getElementById("pad-indicator");
  if (indicator) indicator.hidden = false;
  if (!announced && sessionStorage.getItem("fz-pad") !== "1") {
    announced = true;
    sessionStorage.setItem("fz-pad", "1");
    const pad = firstPad();
    const name = pad && pad.id ? ` (${pad.id.replace(/\s*\(.*$/, "")})` : "";
    const hint = pad && pad.mapping !== "standard" && !loadRemap(pad.id)
      ? " Tasten vertauscht? Select/View, dann „Tasten anlernen“."
      : " Select/View zeigt die Belegung.";
    toast(`Controller verbunden${name}.${hint}`);
    play("connect");
  }
  if (!running) {
    running = true;
    requestAnimationFrame(loop);
  }
}

window.addEventListener("gamepadconnected", start);
window.addEventListener("gamepaddisconnected", () => {
  if (!firstPad()) {
    const indicator = document.getElementById("pad-indicator");
    if (indicator) indicator.hidden = true;
    document.body.classList.remove("pad-mode");
  }
});
// Gamepads that were connected before this page loaded report themselves on the first poll.
// The toast "Controller verbunden" appears once per browser tab, not on every page.
if (firstPad()) start();
window.addEventListener("pointermove", (e) => {
  if (e.pointerType === "mouse" && (Math.abs(e.movementX) + Math.abs(e.movementY) > 2)) {
    document.body.classList.remove("pad-mode");
    document.querySelectorAll(".pad-focus").forEach((n) => n.classList.remove("pad-focus"));
  }
});
document.getElementById("pad-indicator")?.addEventListener("click", () => toggleHelp());
