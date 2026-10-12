import { X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { shortHash } from "../lib/format";
import { useUi } from "../state/ui";

const STATUS_STYLE: Record<string, { color: string; label: string }> = {
  PENDING: { color: "var(--color-idle)", label: "Pending" },
  RUNNING: { color: "var(--color-busy)", label: "Running" },
  SUCCEEDED: { color: "var(--color-ok)", label: "Succeeded" },
  FAILED: { color: "var(--color-fail)", label: "Failed" },
  SKIPPED: { color: "var(--color-idle)", label: "Skipped" },
  CANCELLED: { color: "var(--color-idle)", label: "Cancelled" },
  REUSED: { color: "var(--color-reuse)", label: "Reused" },
};

export function statusColor(status: string | null | undefined, cacheHit = false): string {
  if (cacheHit && status === "SUCCEEDED") return STATUS_STYLE.REUSED!.color;
  return (status && STATUS_STYLE[status]?.color) || "var(--color-rule)";
}

export function StatusBadge({ status, cacheHit = false }: {
  status: string | null | undefined;
  cacheHit?: boolean;
}) {
  if (!status) return <span className="meta">—</span>;
  const key = cacheHit && status === "SUCCEEDED" ? "REUSED" : status;
  const style = STATUS_STYLE[key] ?? { color: "var(--color-idle)", label: status };
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium"
          style={{ color: style.color }}
          title={cacheHit ? "Succeeded by reusing a cached result" : undefined}>
      <span className={`inline-block h-2 w-2 rounded-full ${key === "RUNNING" ? "animate-pulse" : ""}`}
            style={{ background: style.color }} />
      {style.label}
    </span>
  );
}

export function Hash({ value, length = 10 }: { value: string | null | undefined; length?: number }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="meta">—</span>;
  return (
    <button type="button" className="hash cursor-copy hover:text-signal" title={`${value} (click to copy)`}
            onClick={() => {
              void navigator.clipboard?.writeText(value).then(() => {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1200);
              });
            }}>
      {copied ? "copied" : shortHash(value, length)}
    </button>
  );
}

export function EmptyState({ title, children, action }: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-start gap-2 px-6 py-16">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      {children && <div className="text-ink-soft">{children}</div>}
      {action}
    </div>
  );
}

export function KeyValue({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-1.5 text-[13px]">
      {rows.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-ink-faint">{key}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Section({ title, actions, children }: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="border-b border-rule px-4 py-3 last:border-b-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="panel-title">{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-[13px] text-fail">{error instanceof Error ? error.message : String(error)}</p>;
}

export function Toasts() {
  const toasts = useUi((s) => s.toasts);
  const dismiss = useUi((s) => s.dismiss);
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-96 flex-col gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id}
             className={`pointer-events-auto flex items-start gap-2 rounded-md border bg-panel px-3 py-2 text-[13px] shadow-sm ${
               t.tone === "error" ? "border-fail/40 text-fail" : "border-rule text-ink"}`}
             role={t.tone === "error" ? "alert" : "status"}>
          <span className="flex-1">{t.message}</span>
          <button type="button" className="text-ink-faint hover:text-ink" onClick={() => dismiss(t.id)}
                  aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
