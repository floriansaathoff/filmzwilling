// UI sound effects, synthesised with the Web Audio API (no audio files). Can be muted with the
// speaker button in the header; the choice is kept in localStorage.

const KEY = "fz-sound";
let ctx = null;
let master = null;

export const soundOn = () => localStorage.getItem(KEY) !== "0";

export function setSound(on) {
  localStorage.setItem(KEY, on ? "1" : "0");
  if (on) play("select");
}

function audio() {
  if (!soundOn()) return null;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  // Before the first click or key press the browser would refuse (and log a warning).
  if (!ctx && navigator.userActivation && !navigator.userActivation.hasBeenActive) return null;
  if (!ctx) {
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = 0.32;
    master.connect(ctx.destination);
  }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

// Browsers only allow audio after a real user gesture; wake the context on the first one.
for (const type of ["pointerdown", "keydown"]) {
  window.addEventListener(type, () => { if (soundOn()) audio(); }, { once: true, capture: true });
}

/** One enveloped oscillator note. */
function tone(ac, { freq, to = freq, type = "sine", start = 0, dur = 0.08, gain = 0.2, attack = 0.004 }) {
  const t = ac.currentTime + start;
  const osc = ac.createOscillator();
  const env = ac.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t);
  if (to !== freq) osc.frequency.exponentialRampToValueAtTime(to, t + dur);
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(gain, t + attack);
  env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(env).connect(master);
  osc.start(t);
  osc.stop(t + dur + 0.02);
}

/** Short filtered noise burst ("whoosh") for opening and closing layers. */
function whoosh(ac, { dur = 0.22, from = 600, to = 2400, gain = 0.12, start = 0 }) {
  const t = ac.currentTime + start;
  const buffer = ac.createBuffer(1, Math.ceil(ac.sampleRate * dur), ac.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  const src = ac.createBufferSource();
  src.buffer = buffer;
  const filter = ac.createBiquadFilter();
  filter.type = "bandpass";
  filter.Q.value = 1.2;
  filter.frequency.setValueAtTime(from, t);
  filter.frequency.exponentialRampToValueAtTime(to, t + dur);
  const env = ac.createGain();
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(gain, t + dur * 0.35);
  env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(filter).connect(env).connect(master);
  src.start(t);
}

// Pentatonic steps so that every note sounds pleasant; higher notes sound brighter.
const PENTA = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24];
const note = (semi, base = 392) => base * 2 ** (semi / 12);

const SOUNDS = {
  move: (ac) => tone(ac, { freq: 1800, to: 1500, type: "sine", dur: 0.035, gain: 0.05 }),
  select: (ac) => {
    tone(ac, { freq: 660, type: "triangle", dur: 0.07, gain: 0.14 });
    tone(ac, { freq: 990, type: "triangle", start: 0.045, dur: 0.09, gain: 0.12 });
  },
  back: (ac) => {
    tone(ac, { freq: 620, type: "triangle", dur: 0.07, gain: 0.12 });
    tone(ac, { freq: 410, type: "triangle", start: 0.05, dur: 0.1, gain: 0.11 });
  },
  open: (ac) => {
    whoosh(ac, { from: 500, to: 2600 });
    tone(ac, { freq: 523, to: 784, type: "sine", start: 0.04, dur: 0.18, gain: 0.08 });
  },
  close: (ac) => {
    whoosh(ac, { from: 2400, to: 500, dur: 0.18 });
    tone(ac, { freq: 700, to: 460, type: "sine", dur: 0.14, gain: 0.07 });
  },
  page: (ac) => whoosh(ac, { from: 300, to: 3200, dur: 0.3, gain: 0.1 }),
  toggle: (ac) => tone(ac, { freq: 1320, to: 1760, type: "square", dur: 0.04, gain: 0.03 }),
  later: (ac) => tone(ac, { freq: 740, to: 980, type: "sine", dur: 0.12, gain: 0.1 }),
  notSeen: (ac) => {
    tone(ac, { freq: 240, to: 150, type: "sine", dur: 0.16, gain: 0.22 });
    whoosh(ac, { from: 900, to: 300, dur: 0.16, gain: 0.05 });
  },
  undo: (ac) => {
    tone(ac, { freq: 880, to: 520, type: "triangle", dur: 0.14, gain: 0.1 });
  },
  error: (ac) => {
    tone(ac, { freq: 200, type: "sawtooth", dur: 0.12, gain: 0.06 });
    tone(ac, { freq: 160, type: "sawtooth", start: 0.1, dur: 0.16, gain: 0.06 });
  },
  connect: (ac) => [0, 4, 7, 12].forEach((s, i) => tone(ac, { freq: note(s, 523), type: "triangle", start: i * 0.07, dur: 0.18, gain: 0.1 })),
};

/** Play a named UI sound (silently does nothing when muted or unsupported). */
export function play(name) {
  const ac = audio();
  if (!ac || !SOUNDS[name]) return;
  try { SOUNDS[name](ac); } catch { /* audio is a nice-to-have */ }
}

/** Rating chime: pitch rises with the note, 8 and above sparkle. */
export function rate(score) {
  const ac = audio();
  if (!ac) return;
  const n = Math.max(0, Math.min(10, Number(score) || 0));
  tone(ac, { freq: note(PENTA[n]), type: "triangle", dur: 0.22, gain: 0.16 });
  tone(ac, { freq: note(PENTA[n] + 12), type: "sine", start: 0.02, dur: 0.18, gain: 0.05 });
  if (n >= 8) {
    tone(ac, { freq: note(PENTA[n] + 7), type: "sine", start: 0.09, dur: 0.2, gain: 0.08 });
    tone(ac, { freq: note(PENTA[n] + 12), type: "sine", start: 0.16, dur: 0.26, gain: 0.07 });
  }
  if (n <= 2) tone(ac, { freq: note(PENTA[n] - 12), type: "sine", start: 0.03, dur: 0.25, gain: 0.1 });
}
