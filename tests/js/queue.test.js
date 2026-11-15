import { test } from "node:test";
import assert from "node:assert/strict";
import { Preloader, RatingSession, RetryQueue, mergeQueue } from "../../src/filmzwilling/web/static/js/queue.js";

function manualTimers() {
  const timers = [];
  return {
    schedule: (fn, ms) => timers.push({ fn, ms }),
    timers,
    runAll: async () => {
      while (timers.length) {
        const t = timers.shift();
        await t.fn();
      }
    },
  };
}

const tick = () => new Promise((r) => setImmediate(r));

test("retry queue sends in order", async () => {
  const sent = [];
  const q = new RetryQueue({ send: async (r) => { sent.push(r); return true; } });
  q.enqueue("a");
  q.enqueue("b");
  q.enqueue("c");
  await q.idle();
  assert.deepEqual(sent, ["a", "b", "c"]);
  assert.equal(q.size, 0);
});

test("failed requests stay queued, keep order and are retried with backoff", async () => {
  const sent = [];
  let fail = 2;
  const timers = manualTimers();
  const states = [];
  const q = new RetryQueue({
    send: async (r) => {
      sent.push(r);
      if (r === "a" && fail > 0) { fail--; throw new Error("offline"); }
      return true;
    },
    schedule: timers.schedule,
    baseDelay: 100,
    onChange: (s) => states.push(s),
  });
  q.enqueue("a");
  q.enqueue("b");
  await tick();
  assert.equal(q.size, 2);
  assert.equal(q.failures, 1);
  assert.equal(q.lastError, "offline");
  assert.equal(timers.timers[0].ms, 100);
  await timers.runAll();
  await q.idle();
  assert.deepEqual(sent, ["a", "a", "a", "b"]);
  assert.equal(q.size, 0);
  assert.equal(q.failures, 0);
  assert.ok(states.some((s) => s.failures > 0 && s.pending === 2));
  assert.deepEqual(states.at(-1), { pending: 0, failures: 0, lastError: null });
});

test("send returning false counts as failure; backoff grows and is capped", async () => {
  const timers = manualTimers();
  let calls = 0;
  const q = new RetryQueue({
    send: async () => { calls++; return calls > 4; },
    schedule: timers.schedule,
    baseDelay: 100,
    maxDelay: 300,
  });
  q.enqueue({ url: "/api/rate" });
  for (let i = 0; i < 6 && q.size; i++) {
    await tick();
    if (timers.timers.length) await timers.timers.shift().fn();
  }
  await q.idle();
  assert.equal(calls, 5);
  assert.equal(q.size, 0);
});

test("retryNow sends immediately", async () => {
  const timers = manualTimers();
  let ok = false;
  const q = new RetryQueue({ send: async () => ok, schedule: timers.schedule });
  q.enqueue("x");
  await tick();
  assert.equal(q.size, 1);
  ok = true;
  q.retryNow();
  await q.idle();
  assert.equal(q.size, 0);
});

test("preloader loads the next five posters once", () => {
  const loaded = [];
  const p = new Preloader({ load: (u) => loaded.push(u), count: 5 });
  const urls = ["1", "2", "3", "4", "5", "6", "7"];
  assert.deepEqual(p.update(urls), ["1", "2", "3", "4", "5"]);
  assert.deepEqual(p.update(urls.slice(1)), ["6"]);
  assert.deepEqual(loaded, ["1", "2", "3", "4", "5", "6"]);
  assert.equal(p.has("3"), true);
  assert.deepEqual(p.update([null, undefined, "", "8"]), ["8"]);
});

test("mergeQueue skips duplicates and acted films", () => {
  const buffer = [{ film_id: 1 }, { film_id: 2 }];
  const fetched = [{ film_id: 2 }, { film_id: 3 }, { film_id: 4 }, { film_id: 5 }];
  const merged = mergeQueue(buffer, fetched, new Set([4]));
  assert.deepEqual(merged.map((i) => i.film_id), [1, 2, 3, 5]);
  assert.deepEqual(buffer.map((i) => i.film_id), [1, 2]);
});

function makeFetcher(total) {
  const all = Array.from({ length: total }, (_, i) => ({ film_id: i + 1, poster_url: `/p/${i + 1}` }));
  const calls = [];
  return {
    calls,
    fetchBlock: async (limit) => { calls.push(limit); return all.slice(0, limit); },
  };
}

test("rating session advances immediately and preloads", async () => {
  const loaded = [];
  const f = makeFetcher(50);
  const s = new RatingSession({ fetchBlock: f.fetchBlock, preloader: new Preloader({ load: (u) => loaded.push(u) }) });
  await s.start();
  assert.equal(s.current.film_id, 1);
  assert.deepEqual(loaded, ["/p/2", "/p/3", "/p/4", "/p/5", "/p/6"]);
  const rec = s.act("rate", { score: 8 });
  assert.deepEqual(rec, { type: "rate", film_id: 1, score: 8 });
  assert.equal(s.current.film_id, 2);
  assert.equal(loaded.at(-1), "/p/7");
});

test("undo works several times in a row", async () => {
  const f = makeFetcher(50);
  const s = new RatingSession({ fetchBlock: f.fetchBlock });
  await s.start();
  s.act("rate", { score: 5 });
  s.act("not_seen");
  s.act("later");
  assert.equal(s.current.film_id, 4);
  assert.equal(s.upcoming.at(-1).film_id, 3);
  assert.equal(s.undo().film_id, 3);
  assert.equal(s.current.film_id, 3);
  assert.ok(!s.upcoming.some((i) => i.film_id === 3));
  assert.equal(s.undo().film_id, 2);
  assert.equal(s.undo().film_id, 1);
  assert.equal(s.current.film_id, 1);
  assert.equal(s.undo(), null);
});

test("refill fetches blocks of 20 and skips acted films", async () => {
  const f = makeFetcher(100);
  const s = new RatingSession({ fetchBlock: f.fetchBlock, blockSize: 20, refillBelow: 10 });
  await s.start();
  assert.equal(f.calls[0], 20);
  for (let i = 0; i < 11; i++) s.act("rate", { score: 3 });
  assert.equal(s.needsRefill, true);
  await s.refill();
  const ids = [s.current, ...s.upcoming].map((i) => i.film_id);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.every((id) => id > 11));
  assert.ok(ids.length >= 20);
});

test("empty queue gives null current", async () => {
  const s = new RatingSession({ fetchBlock: async () => [] });
  await s.start();
  assert.equal(s.current, null);
  assert.equal(s.act("rate", { score: 1 }), null);
});

test("pending lists unconfirmed requests in order without removing them", async () => {
  const timers = manualTimers();
  const q = new RetryQueue({ send: async () => false, schedule: timers.schedule });
  q.enqueue({ type: "rate", body: { film_id: 1 } });
  q.enqueue({ type: "undo", body: {} });
  await tick();
  assert.deepEqual(q.pending.map((r) => r.type), ["rate", "undo"]);
  q.pending.pop();
  assert.equal(q.size, 2);
});
