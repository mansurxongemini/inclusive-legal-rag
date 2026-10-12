/**
 * Reactive State Store & Pub/Sub Event Hub — Inclusive Legal RAG
 * Zero external dependencies. Replaces scattered window-level globals.
 */

class Store {
  constructor() {
    this._state = {
      currentTab: 'documents',
      stats: null,
      documentsCount: 0,
      normsCount: 0,
      activeKeysCount: 0,
      apiKeysFilter: 'active',
      isSidebarOpen: false
    };

    this._listeners = new Map();
  }

  get(key) {
    return this._state[key];
  }

  set(key, value) {
    const prev = this._state[key];
    if (prev === value) return;

    this._state[key] = value;
    this._notify(key, value, prev);
  }

  update(key, fn) {
    this.set(key, fn(this._state[key]));
  }

  subscribe(key, callback) {
    if (!this._listeners.has(key)) {
      this._listeners.set(key, new Set());
    }
    const set = this._listeners.get(key);
    set.add(callback);

    // Return unsubscribe function
    return () => {
      set.delete(callback);
      if (set.size === 0) {
        this._listeners.delete(key);
      }
    };
  }

  _notify(key, value, prev) {
    const set = this._listeners.get(key);
    if (set) {
      for (const cb of set) {
        try {
          cb(value, prev);
        } catch (err) {
          console.error(`State listener error on [${key}]:`, err);
        }
      }
    }
  }
}

export const store = new Store();
