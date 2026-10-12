import { describe, expect, it } from "vitest";

import { environmentBadge } from "./environment";

describe("environmentBadge", () => {
  it("labels a rebuilt matching environment", () => {
    const badge = environmentBadge("identical", true);
    expect(badge.label).toBe("Rebuilt environment");
    expect(badge.tone).toBe("text-ok");
  });

  it("labels a matching in-place environment", () => {
    expect(environmentBadge("identical", false).label).toBe("Same environment");
  });

  it("labels a differing environment", () => {
    expect(environmentBadge("different", false).label).toBe("Environment differs");
  });

  it("labels an unknown environment", () => {
    expect(environmentBadge("unknown", false).label).toBe("Environment unknown");
  });
});
