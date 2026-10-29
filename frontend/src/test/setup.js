import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Provide standard localStorage mock if jsdom doesn't expose it globally
if (typeof window !== 'undefined') {
  if (!window.localStorage) {
    const store = new Map();
    window.localStorage = {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, val) => store.set(key, String(val)),
      removeItem: (key) => store.delete(key),
      clear: () => store.clear(),
      get length() { return store.size; },
      key: (i) => Array.from(store.keys())[i] ?? null,
    };
  }
  // Ensure globalThis.localStorage points to window.localStorage
  globalThis.localStorage = window.localStorage;
  if (!window.sessionStorage) {
    globalThis.sessionStorage = window.localStorage;
  }
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  try {
    window.localStorage?.clear?.();
    window.sessionStorage?.clear?.();
  } catch {
    // ignore
  }
});

// Polyfill offsetParent for jsdom since jsdom doesn't implement layout
if (typeof HTMLElement !== "undefined") {
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    get() {
      let node = this;
      while (node) {
        if (node.style && (node.style.display === 'none' || node.style.visibility === 'hidden')) {
          return null;
        }
        node = node.parentElement;
      }
      return this.parentElement || document.body;
    },
  });
}

// Polyfill window.matchMedia if not provided by jsdom
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

// Polyfill ResizeObserver
if (typeof window !== 'undefined' && !window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// Polyfill scrollTo / scrollIntoView
if (typeof window !== 'undefined') {
  window.scrollTo = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
}
