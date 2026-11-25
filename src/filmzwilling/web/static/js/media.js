// Trailer helpers without DOM (tested with node --test).

const LANGUAGE_NAMES = { de: "Deutsch", en: "Englisch", fr: "Französisch", es: "Spanisch", it: "Italienisch", ja: "Japanisch" };

/** 75 -> "1:15", 3723 -> "1:02:03"; invalid values -> "0:00". */
export function formatTime(seconds) {
  const total = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function languageName(code) {
  if (!code) return null;
  return LANGUAGE_NAMES[code] || code.toUpperCase();
}

/**
 * Short, unique tab labels for a list of trailers, e.g. ["Trailer · Deutsch", "Trailer · Englisch",
 * "Teaser · Deutsch", "Trailer · Deutsch 2"].
 */
export function trailerLabels(trailers) {
  const seen = new Map();
  return trailers.map((t) => {
    const base = [t.type || "Trailer", languageName(t.language)].filter(Boolean).join(" · ");
    const n = (seen.get(base) || 0) + 1;
    seen.set(base, n);
    return n > 1 ? `${base} ${n}` : base;
  });
}

export const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

/** New playback position after seeking by `delta` seconds, kept inside [0, duration]. */
export function seekTarget(current, delta, duration) {
  const end = Number.isFinite(duration) && duration > 0 ? duration : Infinity;
  return clamp((Number(current) || 0) + delta, 0, end);
}

/** YouTube embed errors that mean "this video cannot be played here": try the next one. */
export function isUnplayableError(code) {
  return [2, 5, 100, 101, 150, 153].includes(Number(code));
}
