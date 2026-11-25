// Data-science page: 3D point clouds (taste space of MovieLens users, film universe) drawn with
// WebGL, plus SVG statistics. Fully usable with a controller: sticks rotate and zoom, D-pad steps
// through points and groups, A opens details, LB/RB switch views.
import { el, formatNumber, getJSON, postJSON, toast } from "./api.js";
import { setAnalogHandler } from "./gamepad.js";
import { Orbit, cycle, pick, project, ramp, ticks } from "./orbit.js";
import { openSheet } from "./sheet.js";

const COLORS = {
  blue: "#338ced",
  orange: "#e76624",
  aqua: "#00a888",
  grey: "#8a8f98",
  red: "#eb6263",
  neutral: "#6b6e75",
};
const TWIN_RAMP = ["#1757ac", "#338ced", "#9dc8f7"];
const NOTE_RAMP = [COLORS.red, COLORS.neutral, COLORS.blue];

const app = document.getElementById("ds-app");
const canvas = document.getElementById("ds-canvas");
const overlay = document.getElementById("ds-overlay");
const ctx = overlay.getContext("2d");
const info = {
  kicker: document.getElementById("ds-kicker"),
  title: document.getElementById("ds-title"),
  text: document.getElementById("ds-text"),
  detail: document.getElementById("ds-detail"),
};
const groupsBox = document.getElementById("ds-groups");
const genreBox = document.getElementById("ds-genres");
const genreLabel = document.getElementById("ds-genre");
const legend = document.getElementById("ds-legend");
const statsBox = document.getElementById("ds-stats");
const tooltip = document.getElementById("ds-tooltip");
const spinBtn = document.getElementById("ds-spin");

const num = (v, d = 0) => (v === null || v === undefined ? "–" : Number(v).toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v, d = 1) => `${formatNumber(v * 100, d)} %`;

// --- WebGL point renderer ---------------------------------------------------------------------
const VERT = `
attribute vec3 aPos; attribute vec3 aColor; attribute float aSize; attribute float aAlpha;
uniform mat4 uMvp; uniform float uScale;
varying vec3 vColor; varying float vAlpha;
void main() {
  gl_Position = uMvp * vec4(aPos, 1.0);
  gl_PointSize = clamp(aSize * uScale / max(gl_Position.w, 0.1), 1.0, 96.0);
  vColor = aColor; vAlpha = aAlpha;
}`;
const FRAG = `
precision mediump float;
varying vec3 vColor; varying float vAlpha;
void main() {
  vec2 c = gl_PointCoord * 2.0 - 1.0;
  float d = dot(c, c);
  if (d > 1.0) discard;
  float core = smoothstep(0.28, 0.0, d);
  float glow = exp(-d * 3.2) - exp(-3.2);
  gl_FragColor = vec4(vColor * (0.7 + 0.5 * core) + core * 0.12, (glow * 0.9 + core * 0.7) * vAlpha);
}`;
const LINE_VERT = `attribute vec3 aPos; uniform mat4 uMvp; void main() { gl_Position = uMvp * vec4(aPos, 1.0); }`;
const LINE_FRAG = `precision mediump float; uniform vec4 uColor; void main() { gl_FragColor = uColor; }`;

function program(gl, vs, fs) {
  const make = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  };
  const p = gl.createProgram();
  gl.attachShader(p, make(gl.VERTEX_SHADER, vs));
  gl.attachShader(p, make(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  return p;
}

class PointRenderer {
  constructor(cv) {
    const gl = cv.getContext("webgl", { antialias: true, premultipliedAlpha: false, preserveDrawingBuffer: true });
    if (!gl) throw new Error("WebGL ist in diesem Browser nicht verfügbar.");
    this.gl = gl;
    this.points = program(gl, VERT, FRAG);
    this.lines = program(gl, LINE_VERT, LINE_FRAG);
    this.buffers = { pos: gl.createBuffer(), color: gl.createBuffer(), size: gl.createBuffer(), alpha: gl.createBuffer(), axes: gl.createBuffer() };
    this.count = 0;
    const a = 1.25;
    const axes = [-a, 0, 0, a, 0, 0, 0, -a, 0, 0, a, 0, 0, 0, -a, 0, 0, a];
    // Equator ring as orientation help.
    for (let i = 0; i < 96; i++) {
      const t0 = (i / 96) * Math.PI * 2;
      const t1 = ((i + 1) / 96) * Math.PI * 2;
      axes.push(Math.cos(t0), 0, Math.sin(t0), Math.cos(t1), 0, Math.sin(t1));
    }
    this.axisCount = axes.length / 3;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.axes);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(axes), gl.STATIC_DRAW);
  }

  upload(name, data) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers[name]);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
  }

  set({ pos, color, size, alpha }) {
    this.count = pos.length / 3;
    this.upload("pos", pos);
    this.upload("color", color);
    this.upload("size", size);
    this.upload("alpha", alpha);
  }

  attrib(prog, name, buffer, n) {
    const gl = this.gl;
    const loc = gl.getAttribLocation(prog, name);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, n, gl.FLOAT, false, 0, 0);
    return loc;
  }

  draw(mvp, scale) {
    const gl = this.gl;
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.disable(gl.DEPTH_TEST);

    gl.useProgram(this.lines);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    const lp = this.attrib(this.lines, "aPos", this.buffers.axes, 3);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.lines, "uMvp"), false, mvp);
    gl.uniform4f(gl.getUniformLocation(this.lines, "uColor"), 1, 1, 1, 0.16);
    gl.drawArrays(gl.LINES, 0, 6);
    gl.uniform4f(gl.getUniformLocation(this.lines, "uColor"), 1, 1, 1, 0.06);
    gl.drawArrays(gl.LINES, 6, this.axisCount - 6);
    gl.disableVertexAttribArray(lp);

    if (!this.count) return;
    gl.useProgram(this.points);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    const locs = [
      this.attrib(this.points, "aPos", this.buffers.pos, 3),
      this.attrib(this.points, "aColor", this.buffers.color, 3),
      this.attrib(this.points, "aSize", this.buffers.size, 1),
      this.attrib(this.points, "aAlpha", this.buffers.alpha, 1),
    ];
    gl.uniformMatrix4fv(gl.getUniformLocation(this.points, "uMvp"), false, mvp);
    gl.uniform1f(gl.getUniformLocation(this.points, "uScale"), scale);
    gl.drawArrays(gl.POINTS, 0, this.count);
    locs.forEach((l) => gl.disableVertexAttribArray(l));
  }
}

// --- state ------------------------------------------------------------------------------------
let data = null;
let renderer = null;
const camera = new Orbit();
let view = "taste";
let cloud = null; // {xs, ys, zs, color, size, alpha, label(i), detail(i), groups, visible(i)}
let groupIndex = 0;
let selected = -1;
let hovered = -1;
let spin = true;
let lastManual = 0;
let genreIndex = -1;
let genres = [];
let width = 0;
let height = 0;
let dpr = 1;

function resize() {
  dpr = Math.min(2, window.devicePixelRatio || 1);
  width = innerWidth;
  height = innerHeight;
  for (const c of [canvas, overlay]) {
    c.width = Math.round(width * dpr);
    c.height = Math.round(height * dpr);
    c.style.width = `${width}px`;
    c.style.height = `${height}px`;
  }
}

// --- building the clouds ----------------------------------------------------------------------
function tasteCloud(t) {
  const n = t.x.length + 1;
  const xs = new Float32Array(n);
  const ys = new Float32Array(n);
  const zs = new Float32Array(n);
  const color = new Float32Array(n * 3);
  const size = new Float32Array(n);
  const alpha = new Float32Array(n);
  const grey = ramp([COLORS.grey, COLORS.grey], 0);
  const twins = [];
  const others = [];
  for (let i = 0; i < n - 1; i++) {
    xs[i] = t.x[i];
    ys[i] = t.y[i];
    zs[i] = t.z[i];
    const r = t.rank[i];
    let c = grey;
    if (r > 0) {
      c = ramp(TWIN_RAMP, 1 - (r - 1) / Math.max(1, t.n_twins - 1));
      size[i] = r <= 20 ? 12 : 7.5;
      alpha[i] = r <= 20 ? 1 : 0.85;
      twins.push(i);
    } else {
      size[i] = 5;
      alpha[i] = 0.5;
      others.push(i);
    }
    color.set(c, i * 3);
  }
  const you = n - 1;
  [xs[you], ys[you], zs[you]] = t.you;
  color.set([1, 1, 1], you * 3);
  size[you] = 24;
  alpha[you] = 1;
  const label = (i) => (i === you ? "Du" : t.rank[i] > 0 ? `Zwilling ${t.rank[i]}` : `MovieLens-Nutzer ${t.ml_user[i]}`);
  const dist = (i) => Math.hypot(xs[i] - xs[you], ys[i] - ys[you], zs[i] - zs[you]);
  return {
    xs, ys, zs, color, size, alpha,
    label,
    you,
    labels: [you, ...twins.slice(0, 3)],
    detail(i) {
      if (i === you) {
        return { kicker: "Du", title: "Dein Geschmack", rows: [["Bewertungen", num(data.summary.ratings)], ["Ø Note", num(data.summary.mean, 1)], ["Zwillinge gefunden", num(data.twins.total)]] };
      }
      const rows = [["MovieLens-Nutzer", String(t.ml_user[i])], ["Abstand zu dir", formatNumber(dist(i), 2)]];
      if (t.rank[i] > 0) rows.unshift(["Ähnlichkeit", formatNumber(t.similarity[i], 3)]);
      const page = data.twin_pages[String(t.ml_user[i])];
      return { kicker: t.rank[i] > 0 ? `Zwilling ${t.rank[i]} von ${num(data.twins.total)}` : "Kein Zwilling", title: label(i), rows, action: page ? "Alle Bewertungen ansehen" : null };
    },
    open(i) {
      const page = i !== you && data.twin_pages[String(t.ml_user[i])];
      if (page) location.href = `/zwillinge/${page}`;
    },
    groups: [
      { label: "Zwillinge", items: twins },
      { label: "Du", items: [you] },
      { label: "Andere", items: others.slice(0, 200) },
    ],
    visible: () => true,
  };
}

function filmCloud(f) {
  const n = f.films.length;
  const xs = Float32Array.from(f.x);
  const ys = Float32Array.from(f.y);
  const zs = Float32Array.from(f.z);
  const color = new Float32Array(n * 3);
  const size = new Float32Array(n);
  const alpha = new Float32Array(n);
  const base = new Float32Array(n);
  const maxCount = Math.max(1, ...f.films.map((m) => m.count));
  f.films.forEach((m, i) => {
    let c;
    if (m.your !== null && m.your !== undefined) {
      c = ramp(NOTE_RAMP, m.your / 10);
      size[i] = 12;
      base[i] = 1;
    } else if (m.rec !== null && m.rec !== undefined) {
      c = ramp([COLORS.aqua, COLORS.aqua], 0);
      size[i] = 7 + Math.max(0, m.rec - 6) * 1.6;
      base[i] = 0.95;
    } else {
      c = ramp([COLORS.grey, COLORS.grey], 0);
      size[i] = 3.5 + 4 * Math.sqrt(m.count / maxCount);
      base[i] = 0.4;
    }
    color.set(c, i * 3);
  });
  const counts = new Map();
  f.films.forEach((m) => m.genres.forEach((g) => counts.set(g, (counts.get(g) || 0) + 1)));
  genres = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([g]) => g);
  const visible = (i) => genreIndex < 0 || f.films[i].genres.includes(genres[genreIndex]);
  const order = (key, dir) => f.films.map((m, i) => i).filter((i) => f.films[i][key] !== null && f.films[i][key] !== undefined).sort((a, b) => dir * (f.films[a][key] - f.films[b][key]) || a - b);
  const label = (i) => f.films[i].title;
  return {
    xs, ys, zs, color, size, alpha, base, label,
    labels: [],
    detail(i) {
      const m = f.films[i];
      const rows = [];
      if (m.your !== null && m.your !== undefined) rows.push(["Deine Note", String(m.your)]);
      if (m.rec !== null && m.rec !== undefined) rows.push(["Vorhersage", formatNumber(m.rec)]);
      rows.push(["MovieLens Ø", `${formatNumber(m.mean)} aus ${num(m.count)}`]);
      if (m.genres.length) rows.push(["Genres", m.genres.join(", ")]);
      return {
        kicker: m.your !== null && m.your !== undefined ? "Von dir bewertet" : m.rec !== null && m.rec !== undefined ? "Empfehlung" : "Film",
        title: m.year ? `${m.title} (${m.year})` : m.title,
        rows,
        action: m.film_id ? "Details" : null,
      };
    },
    open(i) {
      const m = f.films[i];
      if (!m.film_id) return;
      openSheet(
        { film_id: m.film_id, title: m.title, year: m.year, genres: m.genres, poster_url: `/poster/${m.film_id}.svg`, score_text: m.rec !== null && m.rec !== undefined ? formatNumber(m.rec) : null },
        { onRate: async (score) => {
          try {
            await postJSON("/api/rate", { film_id: m.film_id, score, context: "data-science" });
            m.your = score;
            toast(`„${m.title}“ mit ${score} bewertet`);
          } catch (error) {
            toast(error.message, "error");
          }
        } },
      );
    },
    groups: [
      { label: "Deine Top-Filme", items: order("your", -1) },
      { label: "Deine Flops", items: order("your", 1) },
      { label: "Empfehlungen", items: order("rec", -1) },
      { label: "Beliebteste", items: order("count", -1).slice(0, 100) },
    ],
    visible,
    refreshAlpha() {
      for (let i = 0; i < n; i++) alpha[i] = visible(i) ? base[i] : base[i] * 0.06;
    },
  };
}

// --- info panel, legend, groups ---------------------------------------------------------------
const VIEW_TEXT = {
  taste: {
    title: "Geschmacksraum",
    text: (t) => `Jeder Punkt ist ein MovieLens-Nutzer, platziert nach seinem Bewertungsmuster (SVD, 3 Komponenten). Je näher ein Punkt bei dir liegt, desto ähnlicher ist der Geschmack. Gezeigt: ${num(t.x.length)} von ${num(data.dataset.users)} Nutzern, davon ${num(t.n_twins)} Zwillinge.`,
  },
  films: {
    title: "Filmuniversum",
    text: (f) => `Jeder Punkt ist ein Film. Filme, die von denselben Leuten ähnlich bewertet werden, liegen nah beieinander. ${num(f.films.length)} Filme, eingefärbt nach deiner Note.`,
  },
  stats: { title: "Statistik", text: () => "Deine Bewertungen im Vergleich zu MovieLens, deine Zwillinge und wie gut die Vorhersagen sind." },
};

function setInfo(kicker, title, text, rows = [], action = null) {
  info.kicker.textContent = kicker;
  info.title.textContent = title;
  info.text.textContent = text || "";
  info.text.hidden = !text;
  info.detail.replaceChildren(...[
    rows.length ? el("dl", {}, rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })])) : null,
    action ? el("p", { class: "ds-action" }, el("kbd", { class: "pad", text: "A" }), el("span", { class: "mouse-only", text: "Enter / Doppelklick: " }), action) : null,
  ].filter(Boolean));
}

function showViewInfo() {
  const v = VIEW_TEXT[view];
  const payload = view === "taste" ? data.taste : data.films;
  const ex = payload.explained;
  setInfo(
    view === "stats" ? "Überblick" : `Varianz erklärt: ${ex.map((e) => `${formatNumber(e)} %`).join(" · ")}`,
    v.title,
    v.text(payload),
  );
}

function legendItem(swatch, text) {
  return el("li", {}, swatch, el("span", { text }));
}
const dot = (c, s = 12) => el("i", { class: "ds-dot", style: `--c:${c};--s:${s}px` });

function renderLegend() {
  if (view === "taste") {
    legend.replaceChildren(el("ul", {},
      legendItem(dot("#ffffff", 16), "Du"),
      legendItem(el("i", { class: "ds-ramp", style: `--g:linear-gradient(90deg, ${TWIN_RAMP.join(",")})` }), "Zwillinge, heller = ähnlicher"),
      legendItem(dot(COLORS.grey, 8), "Andere MovieLens-Nutzer")));
  } else if (view === "films") {
    legend.replaceChildren(el("ul", {},
      legendItem(el("i", { class: "ds-ramp", style: `--g:linear-gradient(90deg, ${NOTE_RAMP.join(",")})` }), "Deine Note 0 bis 10"),
      legendItem(dot(COLORS.aqua), "Empfehlung"),
      legendItem(dot(COLORS.grey, 8), "Andere Filme, größer = bekannter")));
  }
}

function renderGroups() {
  groupsBox.replaceChildren(
    el("kbd", { class: "pad", text: "↑↓" }),
    ...cloud.groups.map((g, i) => el("button", {
      type: "button", role: "radio", class: "ds-group", "aria-checked": String(i === groupIndex),
      disabled: !g.items.length,
      onclick: () => { groupIndex = i; renderGroups(); step(1, true); },
    }, g.label, el("small", { text: ` ${g.items.filter(cloud.visible).length}` }))),
  );
}

function select(i, { fly = true } = {}) {
  selected = i;
  if (i < 0) {
    showViewInfo();
    return;
  }
  const d = cloud.detail(i);
  setInfo(d.kicker, d.title, "", d.rows, d.action);
  if (fly) camera.focus([cloud.xs[i], cloud.ys[i], cloud.zs[i]], Math.min(camera.goal.distance, 1.6));
}

function step(dir, restart = false) {
  const g = cloud.groups[groupIndex];
  const items = g.items.filter(cloud.visible);
  if (!items.length) {
    toast(`Keine Punkte in „${g.label}“`);
    return;
  }
  const at = restart ? -1 : items.indexOf(selected);
  select(items[cycle(at, dir, items.length)]);
}

function changeGroup(dir) {
  groupIndex = cycle(groupIndex, dir, cloud.groups.length);
  renderGroups();
  step(1, true);
}

function setGenre(dir) {
  if (view !== "films") return;
  genreIndex = genreIndex + dir < -1 ? genres.length - 1 : genreIndex + dir >= genres.length ? -1 : genreIndex + dir;
  genreLabel.textContent = genreIndex < 0 ? "Alle Genres" : genres[genreIndex];
  cloud.refreshAlpha();
  renderer.upload("alpha", cloud.alpha);
  renderGroups();
  if (selected >= 0 && !cloud.visible(selected)) select(-1);
}

function setSpin(on) {
  spin = on;
  spinBtn.setAttribute("aria-pressed", String(on));
}

// --- views ------------------------------------------------------------------------------------
function setView(next) {
  view = next;
  document.querySelectorAll(".ds-view").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === view)));
  const is3d = view !== "stats";
  app.classList.toggle("ds-3d", is3d);
  document.body.classList.toggle("ds-locked", is3d);
  statsBox.hidden = is3d;
  genreBox.hidden = view !== "films";
  tooltip.hidden = true;
  selected = -1;
  hovered = -1;
  history.replaceState(null, "", `#${view}`);
  if (!is3d) {
    renderStats();
    window.scrollTo(0, 0);
    showViewInfo();
    return;
  }
  cloud = view === "taste" ? tasteCloud(data.taste) : filmCloud(data.films);
  if (cloud.refreshAlpha) {
    genreIndex = -1;
    genreLabel.textContent = "Alle Genres";
    cloud.refreshAlpha();
  }
  const pos = new Float32Array(cloud.xs.length * 3);
  for (let i = 0; i < cloud.xs.length; i++) pos.set([cloud.xs[i], cloud.ys[i], cloud.zs[i]], i * 3);
  renderer.set({ pos, color: cloud.color, size: cloud.size, alpha: cloud.alpha });
  groupIndex = 0;
  camera.reset();
  renderGroups();
  renderLegend();
  showViewInfo();
}

function switchView(dir) {
  const views = ["taste", "films", "stats"];
  setView(views[cycle(views.indexOf(view), dir, views.length)]);
}

// --- frame loop -------------------------------------------------------------------------------
let lastFrame = 0;
function frame(now) {
  const dt = Math.min(64, now - (lastFrame || now));
  lastFrame = now;
  if (view !== "stats" && cloud) {
    if (spin && now - lastManual > 2500) camera.rotate(dt * 0.00012, 0);
    camera.step(1 - Math.exp(-dt / 160));
    const mvp = camera.matrix(width / height);
    renderer.draw(mvp, (height * dpr) / 170);
    drawOverlay(mvp, now);
  }
  requestAnimationFrame(frame);
}

function drawOverlay(mvp, now) {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.font = '600 13px "Google Sans", system-ui, sans-serif';
  ctx.textBaseline = "middle";
  const payload = view === "taste" ? data.taste : data.films;
  // Axis labels at the positive ends.
  ctx.fillStyle = "rgba(245,245,247,0.45)";
  [[1.32, 0, 0], [0, 1.32, 0], [0, 0, 1.32]].forEach((p, k) => {
    const s = project(mvp, p, width, height);
    if (s) ctx.fillText(`K${k + 1} · ${formatNumber(payload.explained[k])} %`, s.x + 4, s.y);
  });
  const tag = (i, strong) => {
    const s = project(mvp, [cloud.xs[i], cloud.ys[i], cloud.zs[i]], width, height);
    if (!s) return;
    const text = cloud.label(i);
    const w = ctx.measureText(text).width + 18;
    const x = s.x + 16;
    const y = s.y - 16;
    ctx.strokeStyle = strong ? "rgba(255,255,255,0.75)" : "rgba(255,255,255,0.3)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(s.x + 4, s.y - 4);
    ctx.lineTo(x, y);
    ctx.stroke();
    ctx.fillStyle = strong ? "rgba(245,245,247,0.95)" : "rgba(30,30,30,0.72)";
    ctx.beginPath();
    ctx.roundRect(x, y - 12, w, 24, 12);
    ctx.fill();
    ctx.fillStyle = strong ? "#121212" : "rgba(245,245,247,0.9)";
    ctx.fillText(text, x + 9, y + 1);
  };
  const ring = (i, r, a) => {
    const s = project(mvp, [cloud.xs[i], cloud.ys[i], cloud.zs[i]], width, height);
    if (!s) return;
    ctx.strokeStyle = `rgba(255,255,255,${a})`;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
    ctx.stroke();
  };
  if (cloud.you !== undefined) ring(cloud.you, 16 + 5 * Math.sin(now / 400), 0.35);
  cloud.labels.forEach((i) => i !== selected && tag(i, false));
  if (hovered >= 0 && hovered !== selected) {
    ring(hovered, 11, 0.6);
    tag(hovered, false);
  }
  if (selected >= 0) {
    ring(selected, 14 + 2 * Math.sin(now / 250), 0.95);
    tag(selected, true);
  }
}

// --- statistics (SVG) -------------------------------------------------------------------------
const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, v);
  children.flat(Infinity).forEach((c) => c && node.append(c instanceof Node ? c : document.createTextNode(String(c))));
  return node;
}

function frameChart({ w = 560, h = 250, l = 46, r = 14, t = 14, b = 34 } = {}) {
  return { w, h, l, r, t, b, iw: w - l - r, ih: h - t - b };
}

function axisY(f, yMin, yMax, fmt, label) {
  const scale = (v) => f.t + f.ih - ((v - yMin) / (yMax - yMin || 1)) * f.ih;
  const g = s("g", { class: "ax" }, ticks(yMin, yMax, 4).map((v) => [
    s("line", { x1: f.l, x2: f.l + f.iw, y1: scale(v), y2: scale(v), class: "grid" }),
    s("text", { x: f.l - 8, y: scale(v), "text-anchor": "end", "dominant-baseline": "middle" }, fmt(v)),
  ]), label ? s("text", { x: 4, y: f.t - 2, class: "ax-title" }, label) : null);
  return { g, scale };
}

function axisX(f, xMin, xMax, fmt, label, tickValues = null, log = false) {
  const tr = (v) => (log ? Math.log10(v) : v);
  const scale = (v) => f.l + ((tr(v) - tr(xMin)) / (tr(xMax) - tr(xMin) || 1)) * f.iw;
  const values = tickValues || ticks(xMin, xMax, 5);
  const g = s("g", { class: "ax" }, values.map((v) => s("text", { x: scale(v), y: f.t + f.ih + 18, "text-anchor": "middle" }, fmt(v))),
    s("line", { x1: f.l, x2: f.l + f.iw, y1: f.t + f.ih, y2: f.t + f.ih, class: "base" }),
    label ? s("text", { x: f.l + f.iw, y: f.h - 2, "text-anchor": "end", class: "ax-title" }, label) : null);
  return { g, scale };
}

function card(title, sub, body, { wide = false, keys = null } = {}) {
  return el("article", { class: `ds-card glass-panel${wide ? " wide" : ""}`, tabindex: "0", "data-inspect": body instanceof SVGElement ? "1" : null },
    el("h2", { text: title }), sub ? el("p", { class: "muted ds-sub", text: sub }) : null,
    keys ? el("ul", { class: "ds-keys" }, keys.map(([c, t]) => el("li", {}, dot(c, 10), t))) : null,
    body);
}

function svgRoot(f, label) {
  return s("svg", { viewBox: `0 0 ${f.w} ${f.h}`, class: "ds-chart", role: "img", "aria-label": label });
}

function histogramChart(hist) {
  const f = frameChart();
  const svg = svgRoot(f, "Notenverteilung");
  const yMax = Math.max(...hist.yours_share, ...hist.movielens_share) * 1.12 || 1;
  const y = axisY(f, 0, yMax, (v) => `${Math.round(v * 100)} %`);
  const band = f.iw / 11;
  const bw = (band - 8) / 2;
  svg.append(y.g);
  hist.notes.forEach((n, i) => {
    const x0 = f.l + i * band + 4;
    [["yours_share", COLORS.blue, "Du"], ["movielens_share", COLORS.orange, "MovieLens"]].forEach(([key, c, who], k) => {
      const v = hist[key][i];
      const top = y.scale(v);
      const hgt = Math.max(0, f.t + f.ih - top);
      const extra = key === "yours_share" ? ` (${hist.yours[i]} Filme)` : "";
      svg.append(s("rect", { x: x0 + k * (bw + 2), y: top, width: bw, height: hgt, rx: Math.min(4, hgt / 2), fill: c, class: "mark", "data-tip": `Note ${n} · ${who}: ${pct(v)}${extra}` }));
    });
    svg.append(s("text", { x: x0 + bw + 1, y: f.t + f.ih + 18, "text-anchor": "middle", class: "ax-label" }, String(n)));
  });
  svg.append(s("line", { x1: f.l, x2: f.l + f.iw, y1: f.t + f.ih, y2: f.t + f.ih, class: "base" }));
  return svg;
}

function genreChart(rows, mean) {
  const f = frameChart({ h: Math.max(140, rows.length * 26 + 40), l: 120, b: 26 });
  const svg = svgRoot(f, "Genre-Profil");
  const x = axisX(f, 0, 10, (v) => String(v), null, [0, 2, 4, 6, 8, 10]);
  const bh = Math.min(18, f.ih / rows.length - 6);
  svg.append(x.g);
  rows.forEach((r, i) => {
    const yy = f.t + i * (f.ih / rows.length) + 3;
    svg.append(
      s("text", { x: f.l - 10, y: yy + bh / 2, "text-anchor": "end", "dominant-baseline": "middle", class: "ax-label" }, r.genre),
      s("rect", { x: f.l, y: yy, width: Math.max(2, x.scale(r.mean) - f.l), height: bh, rx: 4, fill: COLORS.blue, class: "mark", "data-tip": `${r.genre}: Ø ${formatNumber(r.mean)} aus ${r.count} Filmen` }),
      s("text", { x: x.scale(r.mean) + 6, y: yy + bh / 2, "dominant-baseline": "middle", class: "val" }, `${formatNumber(r.mean)} · ${r.count}`),
    );
  });
  if (mean !== null && mean !== undefined) {
    svg.append(s("line", { x1: x.scale(mean), x2: x.scale(mean), y1: f.t - 4, y2: f.t + f.ih, class: "ref" }),
      s("text", { x: x.scale(mean), y: f.t - 6, "text-anchor": "middle", class: "val" }, `dein Ø ${formatNumber(mean)}`));
  }
  return svg;
}

function scatterChart(xs, ys, { color, xLabel, yLabel, tip, log = false, yFmt = (v) => formatNumber(v, 2) }) {
  const f = frameChart({ t: 22 });
  const svg = svgRoot(f, `${yLabel} gegen ${xLabel}`);
  if (!xs.length) {
    svg.append(s("text", { x: f.w / 2, y: f.h / 2, "text-anchor": "middle", class: "ax-label" }, "Noch keine Daten"));
    return svg;
  }
  const xMin = log ? Math.max(1, Math.min(...xs)) : Math.min(0, ...xs);
  const xMax = Math.max(...xs) * 1.05;
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const pad = (yMax - yMin) * 0.08 || 0.1;
  let logTicks = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000].filter((v) => v >= xMin && v <= xMax);
  if (logTicks.length < 3) logTicks = [...new Set([Math.round(xMin), ...logTicks, Math.round(xMax / 1.05)])];
  const x = axisX(f, xMin, xMax, (v) => num(v), xLabel, log ? logTicks : null, log);
  const y = axisY(f, yMin - pad, yMax + pad, yFmt, yLabel);
  svg.append(y.g, x.g);
  const g = s("g", {});
  xs.forEach((v, i) => g.append(s("circle", { cx: x.scale(Math.max(xMin, v)), cy: y.scale(ys[i]), r: 4.5, fill: color, "fill-opacity": 0.75, stroke: "#141414", "stroke-width": 1.5, class: "mark", "data-tip": tip(i) })));
  svg.append(g);
  return svg;
}

function timelineChart(points) {
  const f = frameChart({ t: 22 });
  const svg = svgRoot(f, "Bewertungen über die Zeit");
  if (!points.length) return svg;
  const times = points.map((p) => Date.parse(p.at));
  const t0 = times[0];
  const t1 = Math.max(t0 + 60e3, times[times.length - 1]);
  const total = points[points.length - 1].total;
  const xs = (ms) => f.l + ((ms - t0) / (t1 - t0)) * f.iw;
  const y = axisY(f, 0, total * 1.1, (v) => num(v), "Bewertungen gesamt");
  const short = t1 - t0 < 2 * 864e5;
  const fmt = (ms, long = false) => new Date(ms).toLocaleString("de-DE", short && !long ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short", ...(long ? { hour: "2-digit", minute: "2-digit" } : {}) });
  const g = s("g", { class: "ax" }, [t0, (t0 + t1) / 2, t1].map((ms, k) => s("text", { x: xs(ms), y: f.t + f.ih + 18, "text-anchor": ["start", "middle", "end"][k] }, fmt(ms))));
  const pts = points.map((p, i) => [xs(times[i]), y.scale(p.total)]);
  pts.unshift([pts[0][0], y.scale(0)]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  svg.append(y.g, g,
    s("path", { d: `${line}L${pts[pts.length - 1][0].toFixed(1)},${f.t + f.ih}Z`, fill: COLORS.blue, "fill-opacity": 0.18 }),
    s("path", { d: line, fill: "none", stroke: COLORS.blue, "stroke-width": 2, "stroke-linejoin": "round" }),
    s("line", { x1: f.l, x2: f.l + f.iw, y1: f.t + f.ih, y2: f.t + f.ih, class: "base" }));
  const every = Math.max(1, Math.ceil(points.length / 40));
  points.forEach((p, i) => {
    if (i % every && i !== points.length - 1) return;
    svg.append(s("circle", { cx: xs(times[i]), cy: y.scale(p.total), r: 4, fill: COLORS.blue, stroke: "#141414", "stroke-width": 1.5, class: "mark", "data-tip": `${fmt(times[i], true)}: ${num(p.total)} Bewertungen` }));
  });
  return svg;
}

function tile(label, value, sub) {
  return el("div", { class: "ds-tile" }, el("span", { class: "ds-tile-label", text: label }), el("strong", { text: value }), sub ? el("span", { class: "muted", text: sub }) : null);
}

function renderStats() {
  const d = data;
  const ev = d.evaluation;
  const evalBody = ev
    ? el("div", { class: "ds-eval" },
      tile("RMSE (Fehler)", formatNumber(ev.rmse, 2), `Filmdurchschnitt ${formatNumber(ev.baseline_rmse, 2)} · ${formatNumber(Math.abs(1 - ev.rmse / ev.baseline_rmse) * 100, 0)} % ${ev.rmse <= ev.baseline_rmse ? "besser" : "schlechter"}`),
      tile("Spearman (Reihenfolge)", formatNumber(ev.spearman, 2), `Filmdurchschnitt ${formatNumber(ev.baseline_spearman, 2)}`),
      tile("Getestet", num(ev.n_ratings), "eigene Bewertungen, 5-fach"))
    : el("p", { class: "muted", text: "Noch kein Selbsttest. In den Einstellungen „Selbsttest starten“." });
  statsBox.replaceChildren(
    el("div", { class: "ds-tiles" },
      tile("Deine Bewertungen", num(d.summary.ratings)),
      tile("Deine Ø Note", num(d.summary.mean, 1)),
      tile("Zwillinge", num(d.twins.total), "mit genug gemeinsamen Filmen"),
      tile("Empfehlungen", num(d.summary.recs)),
      tile("MovieLens", num(d.dataset.ratings), `Bewertungen von ${num(d.dataset.users)} Nutzern`)),
    el("div", { class: "ds-grid" },
      card("Notenverteilung", "Anteil jeder Note: du gegen alle MovieLens-Bewertungen (umgerechnet auf 0 bis 10).", histogramChart(d.histogram), { keys: [[COLORS.blue, "Du"], [COLORS.orange, "MovieLens"]] }),
      card("Genre-Profil", "Deine Durchschnittsnote je Genre, dahinter die Anzahl Filme.", d.genres.length ? genreChart(d.genres, d.summary.mean) : el("p", { class: "muted", text: "Noch keine Bewertungen." })),
      card("Zwillinge", "Ähnlichkeit gegen gemeinsam bewertete Filme (Top 300). Mehr Überschneidung = verlässlichere Ähnlichkeit.", scatterChart(d.twins.overlap, d.twins.similarity, {
        color: COLORS.blue, xLabel: "gemeinsame Filme", yLabel: "Ähnlichkeit", tip: (i) => `Zwilling ${i + 1}: Ähnlichkeit ${formatNumber(d.twins.similarity[i], 3)}, ${d.twins.overlap[i]} gemeinsame Filme`,
      })),
      card("Empfehlungen", "Vorhergesagte Note gegen Zahl der Zwillinge, die den Film gesehen haben (log).", scatterChart(d.recs.support, d.recs.score, {
        color: COLORS.aqua, xLabel: "Zwillinge (log)", yLabel: "Vorhersage", log: true, yFmt: (v) => formatNumber(v, 1), tip: (i) => `${d.recs.title[i] || "Film"}: ${formatNumber(d.recs.score[i])} von ${d.recs.support[i]} Zwillingen`,
      })),
      card("Bewertungsverlauf", "Wie viele Filme du bisher bewertet hast.", timelineChart(d.timeline)),
      card("Selbsttest", "Kreuzvalidierung: wie genau die App deine Noten vorhersagt.", evalBody),
    ),
  );
}

// Tooltips: mouse hover and controller "inspect" mode (A on a chart, then ←/→).
let inspect = null;
function showTip(mark) {
  document.querySelectorAll(".ds-chart .mark.active").forEach((m) => m.classList.remove("active"));
  if (!mark) {
    tooltip.hidden = true;
    return;
  }
  mark.classList.add("active");
  tooltip.textContent = mark.dataset.tip;
  tooltip.hidden = false;
  const r = mark.getBoundingClientRect();
  const tw = tooltip.offsetWidth;
  tooltip.style.left = `${Math.min(innerWidth - tw - 8, Math.max(8, r.left + r.width / 2 - tw / 2))}px`;
  tooltip.style.top = `${Math.max(8, r.top - tooltip.offsetHeight - 10)}px`;
}
statsBox.addEventListener("pointerover", (e) => {
  const mark = e.target.closest && e.target.closest(".mark");
  if (mark && !inspect) showTip(mark);
});
statsBox.addEventListener("pointerout", (e) => {
  if (!inspect && e.target.closest && e.target.closest(".mark")) showTip(null);
});
function toggleInspect(cardNode) {
  if (inspect) {
    inspect.card.classList.remove("inspecting");
    inspect = null;
    showTip(null);
    return;
  }
  const marks = [...cardNode.querySelectorAll(".mark")];
  if (!marks.length) return;
  inspect = { card: cardNode, marks, i: 0 };
  cardNode.classList.add("inspecting");
  showTip(marks[0]);
}
function inspectStep(dir) {
  inspect.i = cycle(inspect.i, dir, inspect.marks.length);
  showTip(inspect.marks[inspect.i]);
}
statsBox.addEventListener("focusout", (e) => {
  if (inspect && !inspect.card.contains(e.relatedTarget)) toggleInspect();
});

// --- input ------------------------------------------------------------------------------------
document.querySelectorAll(".ds-view").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
document.querySelectorAll(".ds-genre-step").forEach((b) => b.addEventListener("click", () => setGenre(Number(b.dataset.dir))));
spinBtn.addEventListener("click", () => setSpin(!spin));
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.().catch(() => toast("Vollbild ist hier nicht erlaubt."));
}
document.getElementById("ds-fullscreen").addEventListener("click", toggleFullscreen);

let drag = null;
canvas.addEventListener("pointerdown", (e) => {
  drag = { x: e.clientX, y: e.clientY, moved: 0 };
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", (e) => {
  if (drag) {
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    drag.moved += Math.abs(dx) + Math.abs(dy);
    drag.x = e.clientX;
    drag.y = e.clientY;
    camera.rotate(-dx * 0.006, dy * 0.006);
    lastManual = performance.now();
    return;
  }
  if (!cloud) return;
  const m = camera.matrix(width / height);
  hovered = pick(m, cloud.xs, cloud.ys, cloud.zs, e.clientX, e.clientY, width, height, 12, cloud.visible);
  canvas.style.cursor = hovered >= 0 ? "pointer" : "grab";
});
canvas.addEventListener("pointerup", (e) => {
  const click = drag && drag.moved < 6;
  drag = null;
  if (!click || !cloud) return;
  const m = camera.matrix(width / height);
  const i = pick(m, cloud.xs, cloud.ys, cloud.zs, e.clientX, e.clientY, width, height, 14, cloud.visible);
  select(i, { fly: false });
});
canvas.addEventListener("dblclick", () => selected >= 0 && cloud.open && cloud.open(selected));
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  camera.zoom(Math.exp(e.deltaY * 0.0012));
  lastManual = performance.now();
}, { passive: false });

document.addEventListener("keydown", (e) => {
  if (e.target.closest && e.target.closest("input, textarea") || document.querySelector(".sheet-layer, .player, .pad-help") || view === "stats" || !cloud) return;
  const keys = { ArrowLeft: () => step(-1), ArrowRight: () => step(1), ArrowUp: () => changeGroup(-1), ArrowDown: () => changeGroup(1), Enter: () => selected >= 0 && cloud.open && cloud.open(selected), r: () => { camera.reset(); select(-1, { fly: false }); } };
  if (keys[e.key] && !(e.key === "Enter" && e.target.closest && e.target.closest("button, a"))) {
    e.preventDefault();
    keys[e.key]();
  }
});

setAnalogHandler((pad, dt) => {
  if (view === "stats" || !cloud) return false;
  const dz = (v) => (Math.abs(v || 0) < 0.15 ? 0 : v);
  const [lx, ly, , ry] = pad.axes.map(dz);
  if (lx || ly) {
    camera.rotate(-lx * dt * 0.0028, ly * dt * 0.0022);
    lastManual = performance.now();
  }
  if (ry) camera.zoom(Math.exp(ry * dt * 0.0018));
  return true;
});

document.addEventListener("fz:pad", (event) => {
  if (!data || document.querySelector(".sheet-layer")) return;
  const { button } = event.detail;
  const take = (fn) => {
    event.preventDefault();
    fn();
  };
  if (button === "lb") return take(() => switchView(-1));
  if (button === "rb") return take(() => switchView(1));
  if (button === "start") return take(toggleFullscreen);
  if (view === "stats") {
    const focusCard = document.activeElement && document.activeElement.closest && document.activeElement.closest(".ds-card[data-inspect]");
    if (button === "a" && focusCard) return take(() => toggleInspect(focusCard));
    if (inspect && (button === "left" || button === "right")) return take(() => inspectStep(button === "left" ? -1 : 1));
    if (button === "b") return take(() => (inspect ? toggleInspect() : (location.href = "/einstellungen")));
    return;
  }
  const actions = {
    left: () => step(-1),
    right: () => step(1),
    up: () => changeGroup(-1),
    down: () => changeGroup(1),
    a: () => (selected >= 0 && cloud.open ? cloud.open(selected) : selected < 0 ? step(1, true) : null),
    b: () => (selected >= 0 ? (select(-1, { fly: false }), camera.focus([0, 0, 0])) : (location.href = "/einstellungen")),
    x: () => { camera.reset(); select(-1, { fly: false }); },
    y: () => setSpin(!spin),
    lt: () => setGenre(-1),
    rt: () => setGenre(1),
  };
  if (actions[button]) take(actions[button]);
});

window.addEventListener("resize", resize);

async function start() {
  resize();
  if (app.dataset.hasData !== "1") {
    setInfo("Data Science", "Keine Daten", "MovieLens-Daten fehlen. Bitte zuerst „filmzwilling setup“ ausführen.");
    return;
  }
  try {
    renderer = new PointRenderer(canvas);
  } catch (error) {
    setInfo("Data Science", "Kein WebGL", error.message);
    return;
  }
  data = await getJSON("/api/insights");
  app.classList.add("ready");
  const initial = (location.hash || "").slice(1);
  setView(["taste", "films", "stats"].includes(initial) ? initial : "taste");
  requestAnimationFrame(frame);
}

start().catch((error) => {
  setInfo("Data Science", "Fehler", error.message);
  toast(error.message, "error");
});
