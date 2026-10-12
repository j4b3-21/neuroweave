/** Labels for how a reproduction's environment compares to the original. */

export type EnvironmentMatch = "identical" | "different" | "unknown";

export function environmentBadge(
  match: EnvironmentMatch,
  isolated: boolean,
): { label: string; tone: string; title: string } {
  if (match === "identical" && isolated) {
    return {
      label: "Rebuilt environment",
      tone: "text-ok",
      title: "The reproduction ran in a fresh virtual environment rebuilt from the "
        + "original run's lock, and the lock hash matches.",
    };
  }
  if (match === "identical") {
    return {
      label: "Same environment",
      tone: "text-ok",
      title: "The reproduction used an environment whose pinned lock hash matches the original.",
    };
  }
  if (match === "different") {
    return {
      label: "Environment differs",
      tone: "text-busy",
      title: "The pinned environment lock of the reproduction differs from the original. "
        + "Byte-identical outputs still mean the result repeated; they do not mean the "
        + "environments were the same.",
    };
  }
  return {
    label: "Environment unknown",
    tone: "text-ink-soft",
    title: "At least one of the runs has no environment lock, so equality cannot be judged.",
  };
}
