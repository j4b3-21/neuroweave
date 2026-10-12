import { describe, expect, it } from "vitest";

import { formatNodeError } from "./format";

describe("formatNodeError", () => {
  it("does not repeat the exception type the executor already included", () => {
    expect(formatNodeError("RuntimeError: boom", "RuntimeError")).toBe("RuntimeError: boom");
  });

  it("shows messages of skipped or cancelled nodes without a type", () => {
    expect(formatNodeError("Skipped because upstream node(s) a did not succeed.", null))
      .toBe("Skipped because upstream node(s) a did not succeed.");
  });

  it("adds the type when the message does not start with it", () => {
    expect(formatNodeError("boom", "ValueError")).toBe("ValueError: boom");
  });
});
