import { test } from "node:test";
import assert from "node:assert/strict";
import { isEditableTarget, keyToAction } from "../../src/filmzwilling/web/static/js/keys.js";

const body = { tagName: "BODY" };
const ev = (key, extra = {}) => ({ key, code: extra.code ?? "", target: extra.target ?? body, ...extra });

test("digits map to notes 0-9", () => {
  for (let n = 0; n <= 9; n++) {
    assert.deepEqual(keyToAction(ev(String(n), { code: `Digit${n}` })), { type: "rate", score: n });
    assert.deepEqual(keyToAction(ev(String(n), { code: `Numpad${n}` })), { type: "rate", score: n });
  }
});

test("plus (also numpad) and z give 10", () => {
  assert.deepEqual(keyToAction(ev("+")), { type: "rate", score: 10 });
  assert.deepEqual(keyToAction(ev("+", { code: "NumpadAdd" })), { type: "rate", score: 10 });
  assert.deepEqual(keyToAction(ev("z")), { type: "rate", score: 10 });
  assert.deepEqual(keyToAction(ev("Z")), { type: "rate", score: 10 });
});

test("space, s and backspace", () => {
  assert.deepEqual(keyToAction(ev(" ", { code: "Space" })), { type: "not_seen" });
  assert.deepEqual(keyToAction(ev("s")), { type: "later" });
  assert.deepEqual(keyToAction(ev("S")), { type: "later" });
  assert.deepEqual(keyToAction(ev("Backspace")), { type: "undo" });
});

test("other keys and modifiers are ignored", () => {
  assert.equal(keyToAction(ev("a")), null);
  assert.equal(keyToAction(ev("Enter")), null);
  assert.equal(keyToAction(ev("1", { ctrlKey: true })), null);
  assert.equal(keyToAction(ev("z", { metaKey: true })), null);
  assert.equal(keyToAction(ev("s", { altKey: true })), null);
});

test("keys do nothing while an input is focused", () => {
  const inputs = [
    { tagName: "INPUT", type: "text" },
    { tagName: "input", type: "search" },
    { tagName: "TEXTAREA" },
    { tagName: "SELECT" },
    { tagName: "DIV", isContentEditable: true },
  ];
  for (const target of inputs) {
    assert.equal(isEditableTarget(target), true);
    assert.equal(keyToAction(ev("5", { target })), null);
    assert.equal(keyToAction(ev("Backspace", { target })), null);
    assert.equal(keyToAction(ev(" ", { target })), null);
  }
});

test("buttons and checkboxes are not editable", () => {
  assert.equal(isEditableTarget({ tagName: "BUTTON" }), false);
  assert.equal(isEditableTarget({ tagName: "INPUT", type: "checkbox" }), false);
  assert.equal(isEditableTarget({ tagName: "INPUT", type: "radio" }), false);
  assert.equal(isEditableTarget(null), false);
  assert.equal(isEditableTarget(undefined), false);
  assert.deepEqual(keyToAction(ev("3", { target: { tagName: "BUTTON" } })), { type: "rate", score: 3 });
});
