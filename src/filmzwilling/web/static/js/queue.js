// Retry queue, poster preloader and optimistic rating session (no DOM dependency).

/**
 * Sends requests strictly in order. A failing request stays at the head of the queue and is
 * retried with exponential backoff, so later requests (e.g. an undo) never overtake it.
 */
export class RetryQueue {
  constructor({
    send,
    onChange = () => {},
    baseDelay = 500,
    maxDelay = 30000,
    schedule = (fn, ms) => setTimeout(fn, ms),
  }) {
    this._send = send;
    this._onChange = onChange;
    this._baseDelay = baseDelay;
    this._maxDelay = maxDelay;
    this._schedule = schedule;
    this._items = [];
    this._busy = false;
    this._waiting = false;
    this._failures = 0;
    this._lastError = null;
    this._idleResolvers = [];
  }

  get size() { return this._items.length; }
  /** Copy of the requests that are not confirmed yet (oldest first). */
  get pending() { return this._items.slice(); }
  get failures() { return this._failures; }
  get lastError() { return this._lastError; }

  enqueue(request) {
    this._items.push(request);
    this._notify();
    this._pump();
  }

  /** Promise that resolves once every queued request has been sent successfully. */
  idle() {
    if (!this._items.length && !this._busy) return Promise.resolve();
    return new Promise((resolve) => this._idleResolvers.push(resolve));
  }

  retryNow() {
    this._waiting = false;
    this._pump();
  }

  _notify() {
    this._onChange({ pending: this._items.length, failures: this._failures, lastError: this._lastError });
  }

  async _pump() {
    if (this._busy || this._waiting) return;
    this._busy = true;
    while (this._items.length) {
      let ok = false;
      try {
        ok = (await this._send(this._items[0])) !== false;
        if (!ok) this._lastError = "Server hat die Anfrage abgelehnt";
      } catch (error) {
        this._lastError = error && error.message ? error.message : String(error);
      }
      if (!ok) {
        this._failures += 1;
        const delay = Math.min(this._maxDelay, this._baseDelay * 2 ** (this._failures - 1));
        this._waiting = true;
        this._busy = false;
        this._notify();
        this._schedule(() => this.retryNow(), delay);
        return;
      }
      this._items.shift();
      this._failures = 0;
      this._lastError = null;
      this._notify();
    }
    this._busy = false;
    const resolvers = this._idleResolvers.splice(0);
    resolvers.forEach((resolve) => resolve());
  }
}

/** Preloads the next `count` posters exactly once each. */
export class Preloader {
  constructor({ load, count = 5 }) {
    this._load = load;
    this._count = count;
    this._seen = new Set();
  }

  has(url) { return this._seen.has(url); }

  update(urls) {
    const fresh = [];
    for (const url of urls.filter(Boolean).slice(0, this._count)) {
      if (!this._seen.has(url)) {
        this._seen.add(url);
        fresh.push(url);
        this._load(url);
      }
    }
    return fresh;
  }
}

/** Append fetched items to the buffer, skipping duplicates and films already acted on. */
export function mergeQueue(buffer, fetched, skipIds = new Set()) {
  const present = new Set(buffer.map((item) => item.film_id));
  const merged = buffer.slice();
  for (const item of fetched) {
    if (present.has(item.film_id) || skipIds.has(item.film_id)) continue;
    present.add(item.film_id);
    merged.push(item);
  }
  return merged;
}

/**
 * Client-side view of the rating queue: the next film appears immediately after an action,
 * while the request runs in the background.
 */
export class RatingSession {
  constructor({ fetchBlock, blockSize = 20, refillBelow = 10, preloader = null }) {
    this._fetchBlock = fetchBlock;
    this._blockSize = blockSize;
    this._refillBelow = refillBelow;
    this._preloader = preloader;
    this._buffer = [];
    this._history = [];
    this._acted = new Set();
    this._refilling = null;
  }

  get current() { return this._buffer[0] || null; }
  get upcoming() { return this._buffer.slice(1); }
  get historySize() { return this._history.length; }
  get lastAction() { return this._history.length ? this._history[this._history.length - 1].type : null; }
  get needsRefill() { return this._buffer.length < this._refillBelow; }

  async start() {
    const items = await this._fetchBlock(this._blockSize);
    this._buffer = mergeQueue([], items, this._acted);
    this._preload();
  }

  act(type, extra = {}) {
    const item = this.current;
    if (!item) return null;
    this._buffer.shift();
    if (type === "later") {
      this._buffer.push(item);
    } else {
      this._acted.add(item.film_id);
    }
    this._history.push({ type, item });
    this._preload();
    return { type, film_id: item.film_id, ...extra };
  }

  undo() {
    const last = this._history.pop();
    if (!last) return null;
    const { type, item } = last;
    if (type === "later") {
      this._buffer = this._buffer.filter((i) => i.film_id !== item.film_id);
    }
    this._acted.delete(item.film_id);
    this._buffer.unshift(item);
    this._preload();
    return item;
  }

  /** Put an item (e.g. returned by the server's undo) at the front. */
  unshift(item) {
    this._buffer = [item, ...this._buffer.filter((i) => i.film_id !== item.film_id)];
    this._acted.delete(item.film_id);
    this._preload();
  }

  refill(pendingCount = 0) {
    if (this._refilling) return this._refilling;
    const limit = Math.min(100, this._blockSize + this._buffer.length + this._acted.size + pendingCount);
    this._refilling = this._fetchBlock(limit)
      .then((items) => {
        this._buffer = mergeQueue(this._buffer, items, this._acted);
        this._preload();
      })
      .finally(() => { this._refilling = null; });
    return this._refilling;
  }

  _preload() {
    if (this._preloader) {
      this._preloader.update(this._buffer.slice(1).map((i) => i.poster_url));
    }
  }
}
