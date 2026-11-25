// Trailer player: the YouTube stream is embedded with the IFrame API (no YouTube controls,
// youtube-nocookie host) and driven by an own Abyss-style OSD. Keyboard and gamepad work too.
import { el, toast } from "./api.js";
import { clamp, formatTime, isUnplayableError, seekTarget, trailerLabels } from "./media.js";
import { icon, loadMedia, setIcon } from "./ui.js";

const IDLE_MS = 3000;
const YT_STATE = { ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 };

let apiPromise = null;
function loadYouTubeApi() {
  if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
  if (!apiPromise) {
    apiPromise = new Promise((resolve, reject) => {
      const previous = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        if (typeof previous === "function") previous();
        resolve(window.YT);
      };
      const script = document.createElement("script");
      script.src = "https://www.youtube.com/iframe_api";
      script.async = true;
      script.onerror = () => {
        apiPromise = null;
        reject(new Error("YouTube ist nicht erreichbar."));
      };
      document.head.append(script);
      setTimeout(() => reject(new Error("YouTube antwortet nicht.")), 15000);
    });
  }
  return apiPromise;
}

let s = null; // state of the open player

export const isPlayerOpen = () => s !== null;

/** Open the trailer player for a film id (or an object with film_id). */
export async function openTrailer(film) {
  const filmId = film && typeof film === "object" ? film.film_id : film;
  const opener = document.activeElement;
  const media = await loadMedia(filmId);
  if (!media) {
    toast("Trailer konnten nicht geladen werden.", "error");
    return false;
  }
  if (!media.trailers.length) {
    toast(media.online ? "Für diesen Film gibt es keinen Trailer." : "Trailer brauchen TMDB (Offline- oder Demo-Modus).", "error");
    return false;
  }
  if (s) closePlayer();
  build(media, opener);
  return true;
}

function osdButton(name, label, onclick, cls = "") {
  return el("button", { type: "button", class: `osd-btn ${cls}`.trim(), title: label, "aria-label": label, onclick }, icon(name));
}

function build(media, opener) {
  const labels = trailerLabels(media.trailers);
  const ui = {};
  ui.host = el("div", { id: "yt-host" });
  ui.center = el("span", { class: "player-center" }, icon("play"));
  ui.shield = el("div", { class: "player-shield", onclick: () => togglePlay() }, el("span", { class: "player-spinner" }), ui.center);
  ui.message = el("div", { class: "player-message", hidden: true });
  ui.tabs = el("div", { class: "trailer-tabs", role: "tablist", "aria-label": "Trailer wählen" },
    media.trailers.length > 1
      ? labels.map((label, i) => el("button", { type: "button", role: "tab", text: label, onclick: () => switchTrailer(i) }))
      : null);
  ui.cur = el("span", { text: "0:00" });
  ui.rest = el("span", { text: "-0:00" });
  ui.seek = el("input", { type: "range", class: "range", min: "0", max: "1000", step: "1", value: "0", "aria-label": "Position" });
  ui.play = osdButton("pause", "Abspielen/Pause (Leertaste)", () => togglePlay(), "primary");
  ui.next = osdButton("next", "Nächster Trailer (N)", () => switchTrailer((s.index + 1) % s.trailers.length));
  ui.label = el("span", { class: "osd-label" });
  ui.mute = osdButton("volume", "Ton an/aus (M)", () => toggleMute());
  ui.volume = el("input", { type: "range", class: "range osd-volume", min: "0", max: "100", step: "1", value: "100", "aria-label": "Lautstärke" });
  ui.full = osdButton("fullscreen", "Vollbild (F)", () => toggleFullscreen());
  ui.toast = el("div", { class: "player-toast", role: "status" });
  if (media.trailers.length < 2) ui.next.hidden = true;

  const backdrop = media.backdrop_url || media.poster_url;
  const root = el(
    "div",
    { class: "player loading", role: "dialog", "aria-modal": "true", "aria-label": `Trailer: ${media.title}` },
    el("div", { class: "player-bg", style: backdrop ? `background-image:url("${backdrop}")` : null }),
    el("div", { class: "player-stage" }, el("div", { class: "player-frame" }, ui.host, ui.shield)),
    ui.message,
    el("div", { class: "player-top" },
      el("button", { type: "button", class: "btn-round", title: "Schließen (Esc)", "aria-label": "Schließen", onclick: () => closePlayer() }, icon("back")),
      el("div", { class: "player-title" }, media.title, media.year ? el("small", { text: String(media.year) }) : null),
      ui.tabs),
    el("div", { class: "player-osd" },
      el("div", { class: "osd-seek" }, ui.cur, ui.seek, ui.rest),
      el("div", { class: "osd-row" },
        osdButton("rewind", "10 Sekunden zurück (←)", () => seekBy(-10)),
        ui.play,
        osdButton("forward", "10 Sekunden vor (→)", () => seekBy(10)),
        ui.next,
        ui.label,
        el("span", { class: "spacer" }),
        ui.mute,
        ui.volume,
        ui.full)),
    ui.toast,
  );

  s = { root, ui, media, trailers: media.trailers, labels, index: 0, yt: null, opener, dragging: false, timer: null, idleTimer: null, playing: false };
  for (const node of document.body.children) {
    if (node !== root && !node.inert && node.tagName !== "SCRIPT") {
      node.inert = true;
      node.dataset.playerInert = "1";
    }
  }
  document.body.append(root);
  document.body.classList.add("player-open");

  ui.seek.addEventListener("input", () => {
    s.dragging = true;
    const duration = s.yt ? s.yt.getDuration() : 0;
    ui.cur.textContent = formatTime((ui.seek.value / 1000) * duration);
    ui.seek.style.setProperty("--pct", `${ui.seek.value / 10}%`);
  });
  ui.seek.addEventListener("change", () => {
    s.dragging = false;
    if (s.yt) s.yt.seekTo((ui.seek.value / 1000) * s.yt.getDuration(), true);
  });
  ui.volume.addEventListener("input", () => setVolume(Number(ui.volume.value)));
  root.addEventListener("pointermove", wake);
  root.addEventListener("pointerdown", wake);
  document.addEventListener("fullscreenchange", onFullscreen);
  markTrailer();
  ui.play.focus({ preventScroll: true });

  loadYouTubeApi()
    .then((YT) => {
      if (!s || s.root !== root) return;
      s.yt = new YT.Player(ui.host, {
        host: "https://www.youtube-nocookie.com",
        videoId: s.trailers[0].key,
        width: "100%",
        height: "100%",
        playerVars: {
          autoplay: 1, controls: 0, disablekb: 1, fs: 0, iv_load_policy: 3, modestbranding: 1,
          playsinline: 1, rel: 0, cc_load_policy: 0, hl: "de", enablejsapi: 1, origin: location.origin,
        },
        events: { onReady, onStateChange, onError },
      });
    })
    .catch((error) => showMessage(`${error.message} Trailer brauchen eine Internetverbindung.`));
}

function onReady() {
  if (!s) return;
  s.yt.setVolume(Number(s.ui.volume.value));
  s.yt.playVideo();
  s.timer = setInterval(tick, 250);
  // Browsers may block autoplay with sound (e.g. when opened with a controller): play muted then.
  const root = s.root;
  setTimeout(() => {
    if (!s || s.root !== root || !s.yt || s.playing) return;
    s.yt.mute();
    s.yt.playVideo();
    flash("Ton aus: M oder X für Ton");
  }, 1500);
}

function onStateChange(event) {
  if (!s) return;
  const st = event.data;
  s.playing = st === YT_STATE.PLAYING;
  s.root.classList.toggle("loading", st === YT_STATE.BUFFERING || st === -1);
  s.root.classList.toggle("paused", st === YT_STATE.PAUSED || st === YT_STATE.CUED);
  s.root.classList.toggle("ended", st === YT_STATE.ENDED);
  setIcon(s.ui.center.querySelector("svg"), st === YT_STATE.ENDED ? "replay" : "play");
  setIcon(s.ui.play.querySelector("svg"), s.playing || st === YT_STATE.BUFFERING ? "pause" : "play");
  if (s.playing) s.ui.message.hidden = true;
  wake();
}

function onError(event) {
  if (!s) return;
  if (isUnplayableError(event.data) && s.index + 1 < s.trailers.length) {
    flash("Nicht einbettbar, nächster Trailer …");
    switchTrailer(s.index + 1);
    return;
  }
  const key = s.trailers[s.index].key;
  showMessage("Dieser Trailer darf nicht eingebettet abgespielt werden.", `https://www.youtube.com/watch?v=${key}`);
}

function showMessage(text, link) {
  if (!s) return;
  s.root.classList.remove("loading");
  s.ui.message.hidden = false;
  s.ui.message.replaceChildren(el("div", {}, el("p", { text }), link ? el("a", { class: "button secondary", href: link, target: "_blank", rel: "noopener", text: "Auf YouTube ansehen" }) : null));
}

function tick() {
  if (!s || !s.yt || typeof s.yt.getCurrentTime !== "function") return;
  const duration = s.yt.getDuration() || 0;
  const current = s.yt.getCurrentTime() || 0;
  const buffered = (s.yt.getVideoLoadedFraction() || 0) * 100;
  if (!s.dragging) {
    s.ui.cur.textContent = formatTime(current);
    const pct = duration ? (current / duration) * 1000 : 0;
    s.ui.seek.value = String(Math.round(pct));
    s.ui.seek.style.setProperty("--pct", `${pct / 10}%`);
  }
  s.ui.seek.style.setProperty("--buf", `${buffered}%`);
  s.ui.rest.textContent = `-${formatTime(duration - current)}`;
  const muted = s.yt.isMuted() || s.yt.getVolume() === 0;
  setIcon(s.ui.mute.querySelector("svg"), muted ? "mute" : "volume");
  s.ui.volume.style.setProperty("--pct", `${muted ? 0 : s.yt.getVolume()}%`);
  s.ui.volume.style.setProperty("--buf", "0%");
}

function markTrailer() {
  [...s.ui.tabs.children].forEach((b, i) => {
    b.classList.toggle("active", i === s.index);
    b.setAttribute("aria-selected", String(i === s.index));
  });
  s.ui.label.textContent = s.trailers.length > 1 ? `${s.labels[s.index]} (${s.index + 1}/${s.trailers.length})` : s.labels[s.index];
}

function switchTrailer(index) {
  if (!s) return;
  s.index = clamp(index, 0, s.trailers.length - 1);
  markTrailer();
  s.ui.message.hidden = true;
  s.root.classList.add("loading");
  if (s.yt && typeof s.yt.loadVideoById === "function") s.yt.loadVideoById(s.trailers[s.index].key);
}

function togglePlay() {
  if (!s || !s.yt || typeof s.yt.getPlayerState !== "function") return;
  const st = s.yt.getPlayerState();
  if (st === YT_STATE.ENDED) {
    s.yt.seekTo(0, true);
    s.yt.playVideo();
  } else if (st === YT_STATE.PLAYING || st === YT_STATE.BUFFERING) {
    s.yt.pauseVideo();
  } else {
    s.yt.playVideo();
  }
}

function seekBy(delta) {
  if (!s || !s.yt || typeof s.yt.getCurrentTime !== "function") return;
  s.yt.seekTo(seekTarget(s.yt.getCurrentTime(), delta, s.yt.getDuration()), true);
  flash(delta > 0 ? `+${delta} s` : `${delta} s`);
  tick();
}

function setVolume(value) {
  if (!s || !s.yt || typeof s.yt.setVolume !== "function") return;
  const v = clamp(Math.round(value), 0, 100);
  s.yt.setVolume(v);
  s.ui.volume.value = String(v);
  if (v > 0 && s.yt.isMuted()) s.yt.unMute();
  tick();
}

function toggleMute() {
  if (!s || !s.yt || typeof s.yt.isMuted !== "function") return;
  if (s.yt.isMuted()) {
    s.yt.unMute();
    if (s.yt.getVolume() === 0) setVolume(60);
    flash("Ton an");
  } else {
    s.yt.mute();
    flash("Ton aus");
  }
  setTimeout(tick, 50);
}

function toggleFullscreen() {
  if (!s) return;
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else if (s.root.requestFullscreen) s.root.requestFullscreen().catch(() => {});
}

function onFullscreen() {
  if (s) setIcon(s.ui.full.querySelector("svg"), document.fullscreenElement ? "fullscreen-exit" : "fullscreen");
}

function flash(text) {
  if (!s) return;
  s.ui.toast.textContent = text;
  s.ui.toast.classList.add("visible");
  clearTimeout(s.ui.toast._t);
  s.ui.toast._t = setTimeout(() => s && s.ui.toast.classList.remove("visible"), 900);
}

function wake() {
  if (!s) return;
  s.root.classList.remove("idle");
  clearTimeout(s.idleTimer);
  if (s.playing) s.idleTimer = setTimeout(() => s && s.playing && s.root.classList.add("idle"), IDLE_MS);
}

export function closePlayer() {
  if (!s) return;
  const { root, yt, timer, idleTimer, opener } = s;
  s = null;
  clearInterval(timer);
  clearTimeout(idleTimer);
  try { if (yt && typeof yt.destroy === "function") yt.destroy(); } catch { /* already gone */ }
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  document.removeEventListener("fullscreenchange", onFullscreen);
  root.remove();
  document.body.classList.remove("player-open");
  for (const node of document.querySelectorAll("[data-player-inert]")) {
    node.inert = false;
    delete node.dataset.playerInert;
  }
  if (opener && typeof opener.focus === "function" && document.contains(opener)) opener.focus({ preventScroll: true });
}

/**
 * Keyboard while the player is open (like YouTube: Space/K, J/L, arrows, M, F, N, Esc). Runs in
 * the capture phase so page shortcuts never fire; Tab and Enter keep working on the OSD buttons.
 */
window.addEventListener(
  "keydown",
  (event) => {
    if (!s || event.ctrlKey || event.metaKey || event.altKey) return;
    const actions = {
      Escape: () => closePlayer(),
      " ": () => togglePlay(),
      k: () => togglePlay(),
      ArrowLeft: () => seekBy(-10),
      j: () => seekBy(-10),
      ArrowRight: () => seekBy(10),
      l: () => seekBy(10),
      ArrowUp: () => setVolume((s.yt ? s.yt.getVolume() : 100) + 10),
      ArrowDown: () => setVolume((s.yt ? s.yt.getVolume() : 100) - 10),
      m: () => toggleMute(),
      f: () => toggleFullscreen(),
      n: () => switchTrailer((s.index + 1) % s.trailers.length),
      Backspace: () => closePlayer(),
    };
    const action = actions[event.key.length === 1 ? event.key.toLowerCase() : event.key] || actions[event.key];
    wake();
    if (event.key === "Tab" || event.key === "Enter") return;
    event.stopImmediatePropagation();
    if (!action) return;
    event.preventDefault();
    action();
  },
  true,
);

/** Gamepad while the player is open. Returns true if the button was used. */
export function handlePad(button) {
  if (!s) return false;
  wake();
  const map = {
    a: () => togglePlay(),
    start: () => togglePlay(),
    b: () => closePlayer(),
    x: () => toggleMute(),
    y: () => toggleFullscreen(),
    left: () => seekBy(-10),
    right: () => seekBy(10),
    lt: () => seekBy(-30),
    rt: () => seekBy(30),
    up: () => setVolume((s.yt ? s.yt.getVolume() : 100) + 10),
    down: () => setVolume((s.yt ? s.yt.getVolume() : 100) - 10),
    lb: () => switchTrailer((s.index - 1 + s.trailers.length) % s.trailers.length),
    rb: () => switchTrailer((s.index + 1) % s.trailers.length),
  };
  if (map[button]) map[button]();
  return true;
}
