// Orbit camera and point-cloud math without DOM (tested with node --test): matrices for WebGL,
// projection to screen pixels, picking the nearest point and colour ramps.

export function perspective(fovy, aspect, near, far) {
  const f = 1 / Math.tan(fovy / 2);
  const nf = 1 / (near - far);
  return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
function normalize(v) {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
}

export function lookAt(eye, target, up = [0, 1, 0]) {
  const z = normalize(sub(eye, target));
  const x = normalize(cross(up, z));
  const y = cross(z, x);
  return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1];
}

/** Column-major 4x4 product a·b. */
export function multiply(a, b) {
  const out = new Array(16).fill(0);
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      out[c * 4 + r] = s;
    }
  }
  return out;
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Orbit camera: yaw/pitch around a target at a distance; `step` eases towards the goal. */
export class Orbit {
  constructor({ yaw = 0.7, pitch = 0.35, distance = 3.2 } = {}) {
    this.home = { yaw, pitch, distance };
    this.yaw = yaw;
    this.pitch = pitch;
    this.distance = distance;
    this.target = [0, 0, 0];
    this.goal = { target: [0, 0, 0], distance };
  }

  rotate(dYaw, dPitch) {
    this.yaw += dYaw;
    this.pitch = clamp(this.pitch + dPitch, -1.45, 1.45);
  }

  zoom(factor) {
    this.goal.distance = clamp(this.goal.distance * factor, 0.35, 9);
  }

  focus(point, distance) {
    this.goal.target = [...point];
    if (distance) this.goal.distance = clamp(distance, 0.35, 9);
  }

  reset() {
    Object.assign(this, { yaw: this.home.yaw, pitch: this.home.pitch });
    this.goal = { target: [0, 0, 0], distance: this.home.distance };
  }

  /** Ease towards the goal; `t` is the fraction (0..1) to cover this frame. @returns moving? */
  step(t) {
    let moving = false;
    for (let i = 0; i < 3; i++) {
      const d = this.goal.target[i] - this.target[i];
      if (Math.abs(d) > 1e-4) moving = true;
      this.target[i] += d * t;
    }
    const dd = this.goal.distance - this.distance;
    if (Math.abs(dd) > 1e-4) moving = true;
    this.distance += dd * t;
    return moving;
  }

  eye() {
    const cp = Math.cos(this.pitch);
    return [
      this.target[0] + this.distance * cp * Math.sin(this.yaw),
      this.target[1] + this.distance * Math.sin(this.pitch),
      this.target[2] + this.distance * cp * Math.cos(this.yaw),
    ];
  }

  matrix(aspect) {
    return multiply(perspective(0.9, aspect, 0.05, 50), lookAt(this.eye(), this.target));
  }
}

/** Clip-space → screen pixels for one point, or null behind the camera. */
export function project(m, p, width, height) {
  const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
  const y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
  const w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
  if (w <= 0.01) return null;
  return { x: ((x / w + 1) / 2) * width, y: ((1 - y / w) / 2) * height, w };
}

/** Index of the visible point closest to (sx, sy) within `radius` pixels, or -1. */
export function pick(m, xs, ys, zs, sx, sy, width, height, radius = 14, visible = null) {
  let best = -1;
  let bestD = radius * radius;
  for (let i = 0; i < xs.length; i++) {
    if (visible && !visible(i)) continue;
    const s = project(m, [xs[i], ys[i], zs[i]], width, height);
    if (!s) continue;
    const d = (s.x - sx) ** 2 + (s.y - sy) ** 2;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

export function hexToRgb(hex) {
  const v = parseInt(hex.replace("#", ""), 16);
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
}

/** Linear blend of hex colour stops (evenly spaced) at t in 0..1 → [r, g, b] in 0..1. */
export function ramp(stops, t) {
  const rgb = stops.map(hexToRgb);
  const x = clamp(t, 0, 1) * (rgb.length - 1);
  const i = Math.min(rgb.length - 2, Math.floor(x));
  const f = x - i;
  return [0, 1, 2].map((k) => rgb[i][k] + (rgb[i + 1][k] - rgb[i][k]) * f);
}

/** Next index in a cyclic list (dir ±1), starting at 0 or the end when nothing is selected. */
export function cycle(index, dir, length) {
  if (!length) return -1;
  if (index < 0) return dir > 0 ? 0 : length - 1;
  return (index + dir + length) % length;
}

/** Nice axis ticks for [min, max] (about `count` of them). */
export function ticks(min, max, count = 5) {
  if (!(max > min)) return [min];
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((s) => s * mag).find((s) => s >= raw) || raw;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}
