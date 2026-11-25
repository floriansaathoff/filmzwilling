import { test } from "node:test";
import assert from "node:assert/strict";
import { formatTime, isUnplayableError, languageName, seekTarget, trailerLabels } from "../../src/filmzwilling/web/static/js/media.js";

test("formatTime", () => {
  assert.equal(formatTime(0), "0:00");
  assert.equal(formatTime(75.9), "1:15");
  assert.equal(formatTime(3723), "1:02:03");
  assert.equal(formatTime(NaN), "0:00");
  assert.equal(formatTime(-5), "0:00");
});

test("trailer labels are unique and German", () => {
  const labels = trailerLabels([
    { type: "Trailer", language: "de" },
    { type: "Trailer", language: "en" },
    { type: "Trailer", language: "de" },
    { type: "Teaser", language: null },
  ]);
  assert.deepEqual(labels, ["Trailer · Deutsch", "Trailer · Englisch", "Trailer · Deutsch 2", "Teaser"]);
  assert.equal(languageName("pt"), "PT");
});

test("seekTarget stays inside the video", () => {
  assert.equal(seekTarget(5, -10, 120), 0);
  assert.equal(seekTarget(115, 10, 120), 120);
  assert.equal(seekTarget(30, 10, 0), 40);
});

test("unplayable YouTube errors", () => {
  assert.ok(isUnplayableError(150));
  assert.ok(isUnplayableError("101"));
  assert.ok(!isUnplayableError(0));
});
