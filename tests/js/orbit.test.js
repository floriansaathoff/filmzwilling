import assert from "node:assert/strict";
import { test } from "node:test";

import { Orbit, cycle, lookAt, multiply, perspective, pick, project, ramp, ticks } from "../../src/filmzwilling/web/static/js/orbit.js";

const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

test("multiply with identity", () => {
  const m = perspective(1, 1.5, 0.1, 10);
  assert.deepEqual(multiply(I, m), m);
  assert.deepEqual(multiply(m, I), m);
});

test("target projects to the screen centre, points behind the camera vanish", () => {
  const cam = new Orbit({ yaw: 0, pitch: 0, distance: 3 });
  const m = cam.matrix(2);
  const c = project(m, [0, 0, 0], 800, 400);
  assert.ok(Math.abs(c.x - 400) < 1e-6 && Math.abs(c.y - 200) < 1e-6);
  const up = project(m, [0, 0.5, 0], 800, 400);
  assert.ok(up.y < 200, "positive y is up on screen");
  const right = project(m, [0.5, 0, 0], 800, 400);
  assert.ok(right.x > 400, "positive x is right when looking down -z");
  assert.equal(project(m, [0, 0, 10], 800, 400), null);
});

test("lookAt maps the eye to the origin", () => {
  const v = lookAt([1, 2, 3], [0, 0, 0]);
  const p = project(multiply(perspective(1, 1, 0.1, 10), v), [0, 0, 0], 100, 100);
  assert.ok(Math.abs(p.x - 50) < 1e-6);
});

test("orbit clamps pitch and zoom and eases to the goal", () => {
  const cam = new Orbit();
  cam.rotate(0, 10);
  assert.equal(cam.pitch, 1.45);
  cam.zoom(100);
  assert.equal(cam.goal.distance, 9);
  cam.focus([1, 0, 0], 1);
  for (let i = 0; i < 200; i++) cam.step(0.2);
  assert.ok(Math.abs(cam.target[0] - 1) < 1e-3 && Math.abs(cam.distance - 1) < 1e-3);
  assert.equal(cam.step(0.2), false);
  cam.reset();
  assert.deepEqual(cam.goal.target, [0, 0, 0]);
});

test("pick finds the closest visible point", () => {
  const cam = new Orbit({ yaw: 0, pitch: 0, distance: 3 });
  const m = cam.matrix(1);
  const xs = [0, 0.5, -0.5];
  const ys = [0, 0, 0];
  const zs = [0, 0, 0];
  const s = project(m, [0.5, 0, 0], 500, 500);
  assert.equal(pick(m, xs, ys, zs, s.x + 3, s.y, 500, 500), 1);
  assert.equal(pick(m, xs, ys, zs, 5, 5, 500, 500), -1);
  assert.equal(pick(m, xs, ys, zs, s.x, s.y, 500, 500, 14, (i) => i !== 1), -1);
});

test("ramp, cycle and ticks", () => {
  assert.deepEqual(ramp(["#000000", "#ffffff"], 0.5), [0.5, 0.5, 0.5]);
  assert.deepEqual(ramp(["#ff0000", "#00ff00", "#0000ff"], 1), [0, 0, 1]);
  assert.deepEqual(ramp(["#ff0000", "#00ff00"], -3), [1, 0, 0]);
  assert.equal(cycle(-1, 1, 5), 0);
  assert.equal(cycle(-1, -1, 5), 4);
  assert.equal(cycle(4, 1, 5), 0);
  assert.equal(cycle(0, 1, 0), -1);
  assert.deepEqual(ticks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(ticks(0, 1, 4), [0, 0.25, 0.5, 0.75, 1]);
  assert.deepEqual(ticks(3, 3), [3]);
});
