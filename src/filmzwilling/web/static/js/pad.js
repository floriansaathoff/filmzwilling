// Gamepad logic without DOM (tested with node --test): button edges, auto-repeat for directions
// and spatial focus navigation on plain rectangles.

/** Names for the "standard" Gamepad API mapping (Xbox layout; PlayStation: A=Cross, B=Circle …). */
export const BUTTONS = ["a", "b", "x", "y", "lb", "rb", "lt", "rt", "select", "start", "ls", "rs", "up", "down", "left", "right", "home"];
export const DIRECTIONS = ["up", "down", "left", "right"];

const pressed = (button) => Boolean(button && (typeof button === "object" ? button.pressed || button.value > 0.5 : button));

/** Direction of a stick (x, y) or null inside the dead zone. */
export function stickDirection(x, y, deadzone = 0.5) {
  const ax = Math.abs(x || 0);
  const ay = Math.abs(y || 0);
  if (Math.max(ax, ay) < deadzone) return null;
  if (ax > ay) return x > 0 ? "right" : "left";
  return y > 0 ? "down" : "up";
}

/**
 * Turns successive gamepad snapshots into events. Buttons fire once per press; directions
 * (D-pad or left stick) fire on press and then repeat while held, like a keyboard.
 */
export class PadReader {
  constructor({ deadzone = 0.5, delay = 380, repeat = 110 } = {}) {
    this.deadzone = deadzone;
    this.delay = delay;
    this.repeat = repeat;
    this.down = new Set();
    this.dir = null;
    this.nextRepeat = 0;
  }

  /** @param pad {buttons: [{pressed, value}], axes: number[]} @returns [{button, repeat}] */
  read(pad, now) {
    const events = [];
    const buttons = (pad && pad.buttons) || [];
    const axes = (pad && pad.axes) || [];
    const current = new Set();
    buttons.forEach((b, i) => { if (i < BUTTONS.length && pressed(b)) current.add(BUTTONS[i]); });
    for (const name of current) {
      if (!DIRECTIONS.includes(name) && !this.down.has(name)) events.push({ button: name, repeat: false });
    }
    this.down = current;

    const dir = DIRECTIONS.find((d) => current.has(d)) || stickDirection(axes[0], axes[1], this.deadzone);
    if (dir !== this.dir) {
      this.dir = dir;
      if (dir) {
        events.push({ button: dir, repeat: false });
        this.nextRepeat = now + this.delay;
      }
    } else if (dir && now >= this.nextRepeat) {
      events.push({ button: dir, repeat: true });
      this.nextRepeat = now + this.repeat;
    }
    return events;
  }
}

/** Right stick as a scroll vector in pixels per frame (0 inside the dead zone). */
export function scrollVector(pad, speed = 22, deadzone = 0.25) {
  const axes = (pad && pad.axes) || [];
  const f = (v) => (Math.abs(v || 0) < deadzone ? 0 : Math.round((v || 0) * speed));
  return [f(axes[2]), f(axes[3])];
}

/**
 * Index of the best candidate rectangle ({x, y, w, h}) in direction `dir` from `from`, or -1.
 * Candidates must lie in that direction; the score favours small distance along the direction and
 * penalises sideways offset, so moving right in a grid stays in the same row.
 */
export function pickNeighbor(from, candidates, dir) {
  const fcx = from.x + from.w / 2;
  const fcy = from.y + from.h / 2;
  let best = -1;
  let bestScore = Infinity;
  candidates.forEach((c, i) => {
    const ccx = c.x + c.w / 2;
    const ccy = c.y + c.h / 2;
    let main;
    let side;
    let overlap;
    if (dir === "right" || dir === "left") {
      main = dir === "right" ? c.x - (from.x + from.w) : from.x - (c.x + c.w);
      if ((dir === "right" ? ccx - fcx : fcx - ccx) <= 1) return;
      side = Math.abs(ccy - fcy);
      overlap = Math.min(from.y + from.h, c.y + c.h) - Math.max(from.y, c.y);
    } else {
      main = dir === "down" ? c.y - (from.y + from.h) : from.y - (c.y + c.h);
      if ((dir === "down" ? ccy - fcy : fcy - ccy) <= 1) return;
      side = Math.abs(ccx - fcx);
      overlap = Math.min(from.x + from.w, c.x + c.w) - Math.max(from.x, c.x);
    }
    const score = Math.max(main, -Math.min(from.w, from.h) / 2) + side * (overlap > 0 ? 0.6 : 2.5) + (overlap > 0 ? 0 : 400);
    if (score < bestScore) {
      bestScore = score;
      best = i;
    }
  });
  return best;
}

/**
 * Next value of a controller-friendly number stepper. Empty means "no filter": the first step in
 * either direction jumps to `start`; stepping below `min` clears the field again.
 * @returns {string} new input value ("" for no filter)
 */
export function stepNumber(value, dir, { step, start, min, max }) {
  const text = String(value ?? "").trim().replace(",", ".");
  if (text === "" || Number.isNaN(Number(text))) return String(start);
  const decimals = (String(step).split(".")[1] || "").length;
  const next = Number((Number(text) + dir * step).toFixed(decimals));
  if (next < min) return "";
  return String(Math.min(max, next));
}
