// Browser flow for tests/test_e2e.py: node tests/e2e/rate_flow.mjs <base-url>
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const base = process.argv[2];
const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
try {
  await page.goto(base + "/");
  await page.waitForSelector("#film-title:not(:empty)");
  const first = await page.textContent("#film-title");
  const t0 = Date.now();
  await page.keyboard.press("8");
  await page.waitForFunction((t) => document.querySelector("#film-title").textContent !== t, first);
  const switchMs = Date.now() - t0;
  const second = await page.textContent("#film-title");
  await page.keyboard.press("Space");
  await page.waitForFunction((t) => document.querySelector("#film-title").textContent !== t, second);
  await page.keyboard.press("Backspace");
  await page.waitForFunction((t) => document.querySelector("#film-title").textContent === t, second);
  await page.keyboard.press("Backspace");
  await page.waitForFunction((t) => document.querySelector("#film-title").textContent === t, first);
  // Leave the page right away: pending actions are flushed in order (beacon + client ids).
  await page.goto(base + "/bewertungen");
  const progressNow = async () => (await fetch(base + "/api/progress")).json();
  let progress = await progressNow();
  for (let i = 0; i < 50 && (progress.rated !== 0 || progress.not_seen !== 0); i++) {
    await new Promise((r) => setTimeout(r, 100));
    progress = await progressNow();
  }
  if (progress.rated !== 0 || progress.not_seen !== 0) {
    throw new Error("undo after leaving the page was lost: " + JSON.stringify(progress));
  }
  // Typing digits in the search field of another page must not rate anything.
  await page.fill("#rating-search", "123");
  await page.keyboard.press("5");
  await new Promise((r) => setTimeout(r, 300));
  progress = await progressNow();
  if (progress.rated !== 0) throw new Error("typing in an input rated a film: " + JSON.stringify(progress));
  if (errors.length) throw new Error("page errors: " + errors.join("; "));
  console.log(JSON.stringify({ ok: true, switchMs }));
} finally {
  await browser.close();
}
