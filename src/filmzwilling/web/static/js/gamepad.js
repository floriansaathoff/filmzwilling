// Controller support (Gamepad API) on every page: spatial focus navigation with D-pad or left
// stick, A to activate, B to go back, shoulder buttons to switch pages, right stick to scroll.
// Pages can take over buttons by listening for the cancelable "fz:pad" event on document.
import { el, toast } from "./api.js";
import { PadReader, pickNeighbor, scrollVector } from "./pad.js";
import { handlePad as playerPad, isPlayerOpen } from "./player.js";
import { icon } from "./ui.js";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), summary, [tabindex="0"]';
const reader = new PadReader();
let running = false;
let helpLayer = null;
let announced = false;

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
    node.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
  }
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
    const start = defaultTarget(root);
    if (start) focusNode(start);
    return;
  }
  const others = items.filter((n) => n !== current);
  const index = pickNeighbor(rectOf(current), others.map(rectOf), dir);
  if (index >= 0) focusNode(others[index]);
  else if (dir === "up" || dir === "down") {
    const scroller = root === document ? window : root.querySelector(".sheet") || window;
    scroller.scrollBy({ top: (dir === "down" ? 1 : -1) * innerHeight * 0.4, behavior: "smooth" });
  }
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
  node.click();
}

function switchPage(step) {
  const tabs = [...document.querySelectorAll(".tabs .tab")];
  if (!tabs.length) return;
  const current = tabs.findIndex((t) => t.classList.contains("active"));
  const next = tabs[(current + step + tabs.length) % tabs.length];
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
    filters.focus();
    return;
  }
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
}

const HELP = [
  ["Steuerkreuz / linker Stick", "Auswahl bewegen"],
  ["A", "Auswählen, bewerten"],
  ["B", "Zurück, schließen (beim Bewerten: rückgängig)"],
  ["X", "Nicht gesehen (Bewerten)"],
  ["Y", "Trailer abspielen"],
  ["RT", "Später (Bewerten)"],
  ["LB / RB", "Vorherige / nächste Seite"],
  ["Start", "Filter öffnen/schließen (Empfehlungen); X setzt sie zurück"],
  ["Rechter Stick", "Scrollen"],
  ["Im Trailer", "A Pause · ←/→ 10 s · LT/RT 30 s · ↑/↓ Lautstärke · X Ton · Y Vollbild · LB/RB Trailer wechseln · B schließen"],
  ["Select / View", "Diese Hilfe"],
];

function toggleHelp() {
  if (helpLayer) {
    helpLayer.remove();
    helpLayer = null;
    return;
  }
  const close = el("button", { type: "button", class: "secondary", text: "Schließen", onclick: () => toggleHelp() });
  helpLayer = el("div", { class: "pad-help", role: "dialog", "aria-modal": "true", "aria-label": "Controller-Hilfe", onclick: (e) => { if (e.target === helpLayer) toggleHelp(); } },
    el("div", { class: "glass-panel" },
      el("h2", {}, icon("gamepad"), "Controller"),
      el("dl", {}, HELP.flatMap(([keys, text]) => [el("dt", {}, ...keys.split(" / ").flatMap((k, i) => [i ? " / " : null, k.length <= 7 ? el("kbd", { text: k }) : k])), el("dd", { text })])),
      close));
  document.body.append(helpLayer);
  focusNode(close);
}

function route(button) {
  document.body.classList.add("pad-mode");
  if (helpLayer) {
    if (["b", "select", "start"].includes(button)) toggleHelp();
    else if (button === "a") activate();
    else if (["up", "down", "left", "right"].includes(button)) move(button);
    return;
  }
  if (isPlayerOpen() && playerPad(button)) return;
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
  for (const { button } of reader.read(pad, now)) route(button);
  const [dx, dy] = scrollVector(pad);
  if ((dx || dy) && !isPlayerOpen()) {
    const sheet = document.querySelector(".sheet-layer .sheet");
    (sheet || window).scrollBy(dx, dy);
  }
  requestAnimationFrame(loop);
}

function start() {
  const indicator = document.getElementById("pad-indicator");
  if (indicator) indicator.hidden = false;
  if (!announced) {
    announced = true;
    const pad = firstPad();
    toast(`Controller verbunden${pad && pad.id ? ` (${pad.id.replace(/\s*\(.*$/, "")})` : ""}. Select/View zeigt die Belegung.`);
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
if (firstPad()) {
  announced = sessionStorage.getItem("fz-pad") === "1";
  start();
}
window.addEventListener("gamepadconnected", () => sessionStorage.setItem("fz-pad", "1"));
window.addEventListener("pointermove", (e) => {
  if (e.pointerType === "mouse" && (Math.abs(e.movementX) + Math.abs(e.movementY) > 2)) {
    document.body.classList.remove("pad-mode");
    document.querySelectorAll(".pad-focus").forEach((n) => n.classList.remove("pad-focus"));
  }
});
document.getElementById("pad-indicator")?.addEventListener("click", () => toggleHelp());
