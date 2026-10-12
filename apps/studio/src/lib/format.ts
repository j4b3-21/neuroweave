export const shortHash = (value: string | null | undefined, length = 10) =>
  value ? value.slice(0, length) : "—";

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

export function runDuration(start: string | null, end: string | null): number | null {
  if (!start || !end) return null;
  return new Date(end).getTime() - new Date(start).getTime();
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit",
                                minute: "2-digit" });
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MB`;
  return `${(size / 1024 ** 3).toFixed(2)} GB`;
}

export function formatValue(value: unknown): string {
  if (value === undefined) return "unset";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return Math.abs(value) >= 1e5 || (value !== 0 && Math.abs(value) < 1e-3)
    ? value.toExponential(3)
    : String(Math.round(value * 1e6) / 1e6);
}
