import { describe, expect, it } from "vitest";

import { stepsFor, TOUR_STEPS } from "./steps";

describe("stepsFor", () => {
  it("includes tutorial-only steps for tutorial projects", () => {
    const steps = stepsFor(true);
    expect(steps.some((s) => s.id === "bootstrap")).toBe(true);
    expect(steps.length).toBe(TOUR_STEPS.length);
  });

  it("skips tutorial-only steps elsewhere", () => {
    const steps = stepsFor(false);
    expect(steps.some((s) => s.tutorialOnly)).toBe(false);
    expect(steps.some((s) => s.id === "bootstrap")).toBe(false);
    expect(steps.length).toBe(TOUR_STEPS.length - 1);
  });
});
