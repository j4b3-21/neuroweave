import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  dismissWelcome,
  markTourCompleted,
  tourCompleted,
  welcomeDismissed,
} from "./storage";

const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  (globalThis as { window?: unknown }).window = {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value); },
      removeItem: (key: string) => { store.delete(key); },
      clear: () => store.clear(),
    },
  };
});

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("tour storage", () => {
  it("records welcome dismissal", () => {
    expect(welcomeDismissed()).toBe(false);
    dismissWelcome();
    expect(welcomeDismissed()).toBe(true);
  });

  it("records tour completion and dismisses welcome", () => {
    expect(tourCompleted()).toBe(false);
    markTourCompleted();
    expect(tourCompleted()).toBe(true);
    expect(welcomeDismissed()).toBe(true);
  });
});
