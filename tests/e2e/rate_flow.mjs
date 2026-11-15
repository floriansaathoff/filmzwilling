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
  // Typing digits in the search field of another page must not rate anything.
  await page.goto(base + "/bewertungen");
  await page.fill("#rating-search", "123");
  const progress = await (await fetch(base + "/api/progress")).json();
  if (progress.rated !== 0) throw new Error("typing in an input rated a film: " + JSON.stringify(progress));
  if (errors.length) throw new Error("page errors: " + errors.join("; "));
  console.log(JSON.stringify({ ok: true, switchMs }));
} finally {
  await browser.close();
}
