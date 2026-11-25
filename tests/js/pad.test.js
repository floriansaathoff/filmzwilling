import { test } from "node:test";
import assert from "node:assert/strict";
import { PadReader, pickNeighbor, scrollVector, stickDirection } from "../../src/filmzwilling/web/static/js/pad.js";

const snapshot = (pressedNames = [], axes = [0, 0, 0, 0]) => {
  const names = ["a", "b", "x", "y", "lb", "rb", "lt", "rt", "select", "start", "ls", "rs", "up", "down", "left", "right", "home"];
  return { buttons: names.map((n) => ({ pressed: pressedNames.includes(n), value: pressedNames.includes(n) ? 1 : 0 })), axes };
};

test("buttons fire once per press", () => {
  const r = new PadReader();
  assert.deepEqual(r.read(snapshot(["a"]), 0), [{ button: "a", repeat: false }]);
  assert.deepEqual(r.read(snapshot(["a"]), 16), []);
  assert.deepEqual(r.read(snapshot([]), 32), []);
  assert.deepEqual(r.read(snapshot(["a", "y"]), 48), [{ button: "a", repeat: false }, { button: "y", repeat: false }]);
});

test("analog triggers count as pressed above half", () => {
  const r = new PadReader();
  const pad = snapshot();
  pad.buttons[7] = { pressed: false, value: 0.8 };
  assert.deepEqual(r.read(pad, 0), [{ button: "rt", repeat: false }]);
});

test("directions repeat while held (D-pad and stick)", () => {
  const r = new PadReader({ delay: 300, repeat: 100 });
  assert.deepEqual(r.read(snapshot(["right"]), 0), [{ button: "right", repeat: false }]);
  assert.deepEqual(r.read(snapshot(["right"]), 200), []);
  assert.deepEqual(r.read(snapshot(["right"]), 300), [{ button: "right", repeat: true }]);
  assert.deepEqual(r.read(snapshot(["right"]), 350), []);
  assert.deepEqual(r.read(snapshot(["right"]), 400), [{ button: "right", repeat: true }]);
  assert.deepEqual(r.read(snapshot([], [0, 0.9]), 410), [{ button: "down", repeat: false }]);
  assert.deepEqual(r.read(snapshot([], [0, 0.2]), 420), []);
  assert.deepEqual(r.read(snapshot([], [-0.7, 0.1]), 430), [{ button: "left", repeat: false }]);
});

test("stick dead zone and scroll vector", () => {
  assert.equal(stickDirection(0.3, -0.2), null);
  assert.equal(stickDirection(0.1, -0.8), "up");
  assert.deepEqual(scrollVector({ axes: [0, 0, 0.1, -1] }, 20), [0, -20]);
  assert.deepEqual(scrollVector(null), [0, 0]);
});

test("pickNeighbor stays in the row and column of a grid", () => {
  const cell = (col, row) => ({ x: col * 110, y: row * 160, w: 100, h: 150 });
  const grid = [cell(0, 0), cell(1, 0), cell(2, 0), cell(0, 1), cell(1, 1), cell(2, 1)];
  assert.equal(pickNeighbor(grid[0], grid, "right"), 1);
  assert.equal(pickNeighbor(grid[1], grid, "down"), 4);
  assert.equal(pickNeighbor(grid[4], grid, "up"), 1);
  assert.equal(pickNeighbor(grid[3], grid, "left"), -1);
  assert.equal(pickNeighbor(grid[2], grid, "right"), -1);
});

test("pickNeighbor prefers overlapping targets over closer diagonal ones", () => {
  const from = { x: 500, y: 400, w: 60, h: 60 };
  const farBelow = { x: 490, y: 700, w: 80, h: 60 };
  const nearDiagonal = { x: 50, y: 480, w: 60, h: 60 };
  assert.equal(pickNeighbor(from, [nearDiagonal, farBelow], "down"), 1);
  // Moving up from a score button reaches the trailer button even without overlap.
  const trailer = { x: 40, y: 100, w: 140, h: 48 };
  assert.equal(pickNeighbor(from, [trailer], "up"), 0);
});

test("stepNumber: empty jumps to start, below min clears, max caps", async () => {
  const { stepNumber } = await import("../../src/filmzwilling/web/static/js/pad.js");
  const opts = { step: 0.5, start: 6, min: 0, max: 10 };
  assert.equal(stepNumber("", 1, opts), "6");
  assert.equal(stepNumber("", -1, opts), "6");
  assert.equal(stepNumber("6", 1, opts), "6.5");
  assert.equal(stepNumber("6,5", -1, opts), "6");
  assert.equal(stepNumber("9.8", 1, opts), "10");
  assert.equal(stepNumber("0.2", -1, opts), "");
  assert.equal(stepNumber("abc", 1, opts), "6");
  assert.equal(stepNumber("1990", 1, { step: 5, start: 1990, min: 1900, max: 2100 }), "1995");
});

test("hat switch D-pad of generic HID pads", async () => {
  const { hatDirection, hatAxis, PadReader } = await import("../../src/filmzwilling/web/static/js/pad.js");
  assert.equal(hatDirection(-1), "up");
  assert.equal(hatDirection(-3 / 7), "right");
  assert.equal(hatDirection(1 / 7), "down");
  assert.equal(hatDirection(5 / 7), "left");
  assert.equal(hatDirection(9 / 7), null);
  const axes = [0, 0, 0, 0, 0, 0, 0, 0, 0, 9 / 7];
  const pad = { mapping: "", axes, buttons: [] };
  assert.equal(hatAxis(pad), 9);
  assert.equal(hatAxis({ ...pad, mapping: "standard" }), -1);
  const r = new PadReader();
  assert.deepEqual(r.read(pad, 0), []);
  assert.deepEqual(r.read({ ...pad, axes: [...axes.slice(0, 9), -3 / 7] }, 10), [{ button: "right", repeat: false }]);
});

test("remapped buttons and newlyPressed", async () => {
  const { PadReader, newlyPressed } = await import("../../src/filmzwilling/web/static/js/pad.js");
  const b = (...on) => ({ buttons: Array.from({ length: 12 }, (_, i) => ({ pressed: on.includes(i), value: on.includes(i) ? 1 : 0 })), axes: [0, 0] });
  const r = new PadReader({ remap: { a: 2, b: 1, start: 9 } });
  assert.deepEqual(r.read(b(2), 0), [{ button: "a", repeat: false }]);
  assert.deepEqual(r.read(b(2, 0), 10), []);
  assert.deepEqual(r.read(b(9), 20), [{ button: "start", repeat: false }]);
  assert.deepEqual(newlyPressed(b(1), b(1, 4)), [4]);
  assert.deepEqual(newlyPressed(null, b(3)), [3]);
});
