// Browser flow for tests/test_e2e.py: trailer player (with a fake YouTube IFrame API) and
// controller input (with a fake navigator.getGamepads). node tests/e2e/player_pad.mjs <base-url> [shot-dir]
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const base = process.argv[2];
const shotDir = process.argv[3];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));

// Fake YouTube IFrame API: enough of YT.Player for the OSD, records calls.
await page.route("https://www.youtube.com/iframe_api", (route) =>
  route.fulfill({
    contentType: "text/javascript",
    body: `
      window.ytCalls = [];
      class Player {
        constructor(host, opts) {
          this.opts = opts; this.t = 0; this.d = 150; this.state = -1; this.vol = 100; this.muted = false;
          const frame = document.createElement("div");
          frame.id = "fake-yt"; frame.dataset.video = opts.videoId;
          frame.style.cssText = "background:linear-gradient(135deg,#1d2b3a,#3a1d2b);";
          host.replaceWith(frame); this.frame = frame;
          window.ytPlayer = this;
          setTimeout(() => { opts.events.onReady({ target: this }); }, 30);
        }
        set(st) { this.state = st; this.opts.events.onStateChange({ data: st, target: this }); }
        playVideo() { window.ytCalls.push("play"); this.set(1); }
        pauseVideo() { window.ytCalls.push("pause"); this.set(2); }
        seekTo(t) { window.ytCalls.push("seek:" + Math.round(t)); this.t = t; }
        loadVideoById(id) { window.ytCalls.push("load:" + id); this.frame.dataset.video = id; this.set(1); }
        getCurrentTime() { return this.t; } getDuration() { return this.d; }
        getVideoLoadedFraction() { return 0.4; } getPlayerState() { return this.state; }
        setVolume(v) { this.vol = v; } getVolume() { return this.vol; }
        mute() { this.muted = true; } unMute() { this.muted = false; } isMuted() { return this.muted; }
        destroy() { window.ytCalls.push("destroy"); this.frame.remove(); }
      }
      window.YT = { Player };
      window.onYouTubeIframeAPIReady && window.onYouTubeIframeAPIReady();`,
  }),
);
// The demo is offline, so give every film two trailers and a backdrop-less media answer.
await page.route(/\/api\/films\/\d+\/media$/, async (route) => {
  const response = await route.fetch();
  const body = await response.json();
  body.trailers = [
    { key: "trailerDE01", name: "Trailer (Deutsch)", language: "de", type: "Trailer", official: true },
    { key: "trailerEN01", name: "Official Trailer", language: "en", type: "Trailer", official: true },
  ];
  body.overview = "Ein Testfilm mit Trailer. Die Handlung ist erfunden, der Player ist echt.";
  route.fulfill({ response, json: body });
});

// Fake gamepad: tests press buttons through window.pad.press(name).
await page.addInitScript(() => {
  const names = ["a", "b", "x", "y", "lb", "rb", "lt", "rt", "select", "start", "ls", "rs", "up", "down", "left", "right", "home"];
  const pad = { id: "Test Controller (STANDARD GAMEPAD)", index: 0, connected: true, mapping: "standard", axes: [0, 0, 0, 0], buttons: names.map(() => ({ pressed: false, value: 0 })) };
  navigator.getGamepads = () => [pad];
  window.pad = {
    async press(name) {
      const b = pad.buttons[names.indexOf(name)];
      b.pressed = true; b.value = 1;
      await new Promise((r) => setTimeout(r, 100));
      b.pressed = false; b.value = 0;
      await new Promise((r) => setTimeout(r, 60));
    },
  };
});

const progress = async () => (await fetch(base + "/api/progress")).json();
const calls = () => page.evaluate(() => window.ytCalls || []);
const press = (name) => page.evaluate((n) => window.pad.press(n), name);

try {
  await page.goto(base + "/");
  await page.waitForSelector("#film-title:not(:empty)");
  await page.waitForSelector("#pad-indicator:not([hidden])");
  const first = await page.textContent("#film-title");

  // Keyboard T opens the trailer; the OSD drives the fake player.
  await page.keyboard.press("t");
  await page.waitForSelector(".player #fake-yt");
  await page.waitForFunction(() => (window.ytCalls || []).includes("play"));
  if (await page.textContent(".player-title") === "") throw new Error("no title in player");
  // Rating keys must not reach the rating page while the player is open.
  await page.keyboard.press("8");
  await page.keyboard.press("ArrowRight");
  if (!(await calls()).includes("seek:10")) throw new Error("arrow right did not seek: " + (await calls()));
  if ((await progress()).rated !== 0) throw new Error("digit rated a film while the player was open");
  await page.click(".trailer-tabs button:nth-child(2)");
  if (!(await calls()).includes("load:trailerEN01")) throw new Error("trailer tab did not switch");
  await page.keyboard.press(" ");
  if (!(await calls()).includes("pause")) throw new Error("space did not pause");
  await page.waitForSelector(".player.paused .player-center");
  if (shotDir) await page.screenshot({ path: `${shotDir}/player-paused.png` });
  await page.keyboard.press(" ");
  await page.waitForTimeout(300);
  if (shotDir) await page.screenshot({ path: `${shotDir}/player.png` });
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector(".player"));
  if (!(await calls()).includes("destroy")) throw new Error("player not destroyed");

  // Controller on the rating page: D-pad to a score, A rates, X = not seen, B = undo, Y = trailer.
  await press("right");
  await page.waitForFunction(() => document.body.classList.contains("pad-mode"), null, { timeout: 5000 }).catch(() => { throw new Error("no pad-mode; page errors: " + errors.join("; ")); });
  const focused = await page.evaluate(() => document.activeElement && document.activeElement.dataset.score);
  if (focused !== "5") throw new Error("first D-pad press should focus score 5, got " + focused);
  await press("right");
  await press("right");
  await press("a");
  await page.waitForFunction((t) => document.querySelector("#film-title").textContent !== t, first);
  let p = await progress();
  for (let i = 0; i < 30 && p.rated !== 1; i++) { await new Promise((r) => setTimeout(r, 100)); p = await progress(); }
  if (p.rated !== 1) throw new Error("A did not rate: " + JSON.stringify(p));
  const ratings = await (await fetch(base + "/api/ratings")).json();
  if (ratings.items[0].score !== 7) throw new Error("expected score 7, got " + ratings.items[0].score);
  const second = await page.textContent("#film-title");
  await press("x");
  await page.waitForFunction((t) => document.querySelector("#film-title").textContent !== t, second);
  await press("b");
  await page.waitForFunction((t) => document.querySelector("#film-title").textContent === t, second);
  await press("y");
  await page.waitForSelector(".player #fake-yt");
  await page.waitForFunction(() => (window.ytCalls || []).filter((c) => c === "play").length >= 2);
  await press("right");
  await press("b");
  await page.waitForFunction(() => !document.querySelector(".player"));
  // Select shows the controller help.
  await press("select");
  await page.waitForSelector(".pad-help", { timeout: 5000 }).catch(() => { throw new Error("no help; page errors: " + errors.join("; ")); });
  if (shotDir) await page.screenshot({ path: `${shotDir}/pad-help.png` });
  await press("b");
  await page.waitForFunction(() => !document.querySelector(".pad-help"));
  // A clicked note must not stay highlighted (white) after the film has changed.
  await page.mouse.move(5, 5);
  await page.mouse.move(400, 300);
  await page.click('.score[data-score="3"]');
  await page.mouse.move(5, 5);
  await page.waitForTimeout(700);
  const stuck = await page.evaluate(() => {
    const b = document.querySelector('.score[data-score="3"]');
    return { pressed: b.classList.contains("pressed"), bg: getComputedStyle(b).backgroundColor };
  });
  if (stuck.pressed || stuck.bg.startsWith("rgb(245") || stuck.bg.startsWith("rgb(255")) {
    throw new Error("clicked note stays highlighted: " + JSON.stringify(stuck));
  }
  // RB switches to the next page.
  await press("rb").catch(() => {}); // the page navigates away while the press is running
  await page.waitForURL(base + "/empfehlungen");
  // Filters with the controller: Start opens them, steppers work with A, X resets, B closes.
  await page.waitForSelector("#pad-indicator:not([hidden])");
  await press("start");
  await page.waitForSelector("#filters:not([hidden])");
  if (!(await page.evaluate(() => document.getElementById("filters").contains(document.activeElement)))) {
    throw new Error("Start did not move the focus into the filters");
  }
  await press("a");
  if (!(await page.evaluate(() => document.getElementById("providers-any").checked))) throw new Error("A did not toggle the chip");
  await page.focus('.stepper:first-child [data-dir="1"]');
  await press("a");
  await press("a");
  const minScore = await page.inputValue('input[name="min_score"]');
  if (minScore !== "6.5") throw new Error("stepper: expected 6.5, got " + minScore);
  await page.waitForFunction(() => location.search.includes("min_score=6.5"));
  if (shotDir) await page.screenshot({ path: `${shotDir}/filters-pad.png` });
  await press("x");
  await page.waitForFunction(() => document.querySelector('input[name="min_score"]').value === "");
  await press("b");
  await page.waitForSelector("#filters", { state: "hidden" });
  if (errors.length) throw new Error("page errors: " + errors.join("; "));
  console.log(JSON.stringify({ ok: true }));
} finally {
  await browser.close();
}
