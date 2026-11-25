// Browser flow for tests/test_e2e.py: settings and data-science page with a fake controller.
// node tests/e2e/datascience_pad.mjs <base-url> [shot-dir]
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const base = process.argv[2];
const shotDir = process.argv[3];
const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));

await page.addInitScript(() => {
  const names = ["a", "b", "x", "y", "lb", "rb", "lt", "rt", "select", "start", "ls", "rs", "up", "down", "left", "right", "home"];
  const pad = { id: "Test Controller (STANDARD GAMEPAD)", index: 0, connected: true, mapping: "standard", axes: [0, 0, 0, 0], buttons: names.map(() => ({ pressed: false, value: 0 })) };
  navigator.getGamepads = () => [pad];
  window.pad = {
    async press(name) {
      const b = pad.buttons[names.indexOf(name)];
      b.pressed = true; b.value = 1;
      // Headless Chromium can skip frames for up to 275 ms: hold long enough to be seen.
      await new Promise((r) => setTimeout(r, 250));
      b.pressed = false; b.value = 0;
      await new Promise((r) => setTimeout(r, 60));
    },
    axes(values) { pad.axes = values; },
  };
});

const api = async (path, body) => (await fetch(base + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {})).json();
// Navigation destroys the page context while a press is still running: that is expected.
const press = (name) => page.evaluate((n) => window.pad.press(n), name).catch(() => {});
const shot = (name) => shotDir && page.screenshot({ path: `${shotDir}/${name}.png` });
const check = (cond, message) => { if (!cond) throw new Error(message); };

try {
  // 40 ratings so that there are twins and recommendations.
  const items = (await api("/api/queue?limit=40")).items;
  for (const [i, item] of items.entries()) await api("/api/rate", { film_id: item.film_id, score: (i * 7) % 11 });
  await api("/api/recompute", {});

  await page.goto(base + "/einstellungen");
  await page.waitForSelector("#providers .chip-toggle");
  // First D-pad press focuses the data-science entry; the stepper changes the queue size.
  await press("down");
  check(await page.evaluate(() => document.activeElement.id) === "open-data-science", "data-science entry is not the default focus");
  await page.click(".queue-stepper [data-dir='1']");
  await page.waitForFunction(() => document.getElementById("settings-status").dataset.kind === "ok");
  check((await api("/api/settings")).queue_size === 1050, "queue stepper did not save");
  await shot("settings");

  await page.focus("#open-data-science");
  await press("a");
  await page.waitForFunction(() => location.pathname === "/data-science" && document.getElementById("ds-app")?.classList.contains("ready"));
  check(await page.evaluate(() => getComputedStyle(document.querySelector(".topbar")).display === "none"), "tab bar is visible on the full-screen page");
  await press("right");
  const title = await page.textContent("#ds-title");
  check(title.startsWith("Zwilling 1"), `D-pad right did not select twin 1: ${title}`);
  // Analog sticks rotate the view and do not move the focus.
  const before = await page.evaluate(() => document.activeElement.tagName);
  await page.evaluate(() => window.pad.axes([0.9, 0, 0, 0]));
  await page.waitForTimeout(300);
  await page.evaluate(() => window.pad.axes([0, 0, 0, 0]));
  check(await page.evaluate(() => document.activeElement.tagName) === before, "left stick moved the focus");
  await shot("ds-taste");
  check((await page.textContent("#ds-detail")).includes("Alle Bewertungen"), "twin 1 offers no twin page");

  await press("rb");
  check(await page.getAttribute(".ds-view[data-view='films']", "aria-selected") === "true", "RB did not switch to the film universe");
  await press("right");
  check((await page.textContent("#ds-kicker")) === "Von dir bewertet", "first film in 'Deine Top-Filme' is not a rated film");
  await press("a");
  await page.waitForSelector(".sheet-layer");
  await press("b");
  await page.waitForFunction(() => !document.querySelector(".sheet-layer"));
  await press("rt");
  check((await page.textContent("#ds-genre")) !== "Alle Genres", "RT did not pick a genre");
  await shot("ds-films");

  await press("rb");
  await page.waitForSelector("#ds-stats .ds-chart");
  check((await page.$$("#ds-stats .ds-card")).length === 6, "statistics cards missing");
  await press("down");
  await press("down");
  await press("a");
  await press("right");
  check(await page.evaluate(() => !document.getElementById("ds-tooltip").hidden), "inspect mode shows no tooltip");
  await shot("ds-stats");
  await press("b");
  await press("b");
  await page.waitForURL("**/einstellungen");
  check(!errors.length, "page errors: " + errors.join("; "));
  console.log(JSON.stringify({ ok: true }));
} finally {
  await browser.close();
}
