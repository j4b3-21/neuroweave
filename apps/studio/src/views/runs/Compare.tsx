import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { api } from "../../api/client";
import type { MetricComparison, NodeComparison } from "../../api/types";
import { ErrorText, Hash, Section, StatusBadge } from "../../components/common";
import { formatDuration, formatNumber, formatValue } from "../../lib/format";

function better(metric: MetricComparison): "a" | "b" | null {
  if (metric.delta === null || metric.delta === 0 || !metric.direction) return null;
  if (metric.direction === "maximize") return metric.delta > 0 ? "b" : "a";
  if (metric.direction === "minimize") return metric.delta < 0 ? "b" : "a";
  return null;
}

function changes(node: NodeComparison): string[] {
  const notes: string[] = [];
  if (!node.in_a) notes.push("only in B");
  if (!node.in_b) notes.push("only in A");
  if (node.definition[0] !== node.definition[1] && node.in_a && node.in_b) notes.push("node type changed");
  if (node.version[0] !== node.version[1] && node.in_a && node.in_b) {
    notes.push(`version ${node.version[0]} to ${node.version[1]}`);
  }
  if (node.code_changed) notes.push("source code changed");
  for (const [name, [a, b]] of Object.entries(node.param_changes)) {
    notes.push(`${name}: ${formatValue(a)} to ${formatValue(b)}`);
  }
  for (const name of Object.keys(node.input_changes)) notes.push(`input '${name}' differs`);
  return notes;
}

export function Compare({ a, b, onClose }: { a: string; b: string; onClose: () => void }) {
  const comparison = useQuery({ queryKey: ["compare", a, b], queryFn: () => api.compare(a, b) });
  if (comparison.error) return <div className="p-4"><ErrorText error={comparison.error} /></div>;
  if (!comparison.data) return <p className="meta p-6">Comparing runs…</p>;
  const c = comparison.data;
  const diff = c.workflow_diff;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-panel">
      <header className="flex items-start gap-3 border-b border-rule px-4 py-3">
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[13px]">
          <span className="font-semibold">A</span>
          <span className="flex items-center gap-2"><span className="hash">{c.run_a.id}</span>
            <StatusBadge status={c.run_a.status} /> <span className="meta">seed {c.seed[0]}</span></span>
          <span className="font-semibold">B</span>
          <span className="flex items-center gap-2"><span className="hash">{c.run_b.id}</span>
            <StatusBadge status={c.run_b.status} /> <span className="meta">seed {c.seed[1]}</span></span>
        </div>
        <button type="button" className="btn btn-quiet ml-auto" onClick={onClose}>
          <X size={14} /> Close comparison
        </button>
      </header>

      <Section title="Summary">
        <ul className="list-disc pl-5 text-[13px]">
          {c.summary.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </Section>

      {!c.same_snapshot && (
        <Section title="Workflow changes">
          {diff.identical ? <p className="meta">No semantic differences (layout only).</p> : (
            <ul className="flex flex-col gap-0.5 text-[13px]">
              {diff.nodes_added.map((n) => <li key={`+${n}`} className="text-ok">+ node {n}</li>)}
              {diff.nodes_removed.map((n) => <li key={`-${n}`} className="text-fail">- node {n}</li>)}
              {diff.edges_added.map((e) => <li key={`+${e}`} className="font-mono text-[12px] text-ok">+ {e}</li>)}
              {diff.edges_removed.map((e) => <li key={`-${e}`} className="font-mono text-[12px] text-fail">- {e}</li>)}
              {diff.nodes_changed.map((n) => (
                <li key={n.node_id}>
                  ~ {n.node_id}: {[
                    ...(n.type_change ? [`type ${n.type_change[0]} to ${n.type_change[1]}`] : []),
                    ...Object.entries(n.param_changes).map(([k, [x, y]]) => `${k} ${formatValue(x)} to ${formatValue(y)}`),
                    ...(n.label_change ? ["label"] : []),
                  ].join(", ")}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      <Section title="Metrics">
        {c.metrics.length === 0 ? <p className="meta">Neither run logged metrics.</p> : (
          <table className="data-table">
            <thead><tr><th>Node</th><th>Metric</th><th>A</th><th>B</th><th>Change (B minus A)</th></tr></thead>
            <tbody>
              {c.metrics.map((m) => {
                const winner = better(m);
                return (
                  <tr key={`${m.node_id}.${m.name}`}>
                    <td className="font-mono text-[12px]">{m.node_id}</td>
                    <td>{m.name}{m.direction && <span className="meta"> ({m.direction})</span>}</td>
                    <td className={`font-mono ${winner === "a" ? "font-semibold text-ok" : ""}`}>{formatNumber(m.a)}</td>
                    <td className={`font-mono ${winner === "b" ? "font-semibold text-ok" : ""}`}>{formatNumber(m.b)}</td>
                    <td className="font-mono">{m.delta === null ? "—" : `${m.delta > 0 ? "+" : ""}${formatNumber(m.delta)}`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Nodes">
        <table className="data-table">
          <thead><tr><th>Node</th><th>A</th><th>B</th><th>Duration A / B</th><th>What changed</th><th>Outputs</th></tr></thead>
          <tbody>
            {c.nodes.map((node) => {
              const notes = changes(node);
              const outputs = Object.entries(node.outputs);
              return (
                <tr key={node.node_id}>
                  <td className="font-mono text-[12px]">{node.node_id}</td>
                  <td><StatusBadge status={node.status[0]} cacheHit={Boolean(node.cache_hit[0])} /></td>
                  <td><StatusBadge status={node.status[1]} cacheHit={Boolean(node.cache_hit[1])} /></td>
                  <td className="text-[12px]">{formatDuration(node.duration_ms[0])} / {formatDuration(node.duration_ms[1])}</td>
                  <td className="text-[12px]">{notes.length ? notes.join("; ") : <span className="text-ink-faint">nothing</span>}</td>
                  <td className="text-[12px]">
                    {outputs.map(([port, o]) => (
                      <div key={port} className="flex items-center gap-1.5">
                        <span>{port}</span>
                        {o.identical ? <span className="text-ok">identical</span> : (
                          <span className="flex items-center gap-1 text-busy">
                            differs <Hash value={o.a} length={8} /> / <Hash value={o.b} length={8} />
                          </span>
                        )}
                      </div>
                    ))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Section>

      <Section title="Environment differences">
        {Object.keys(c.environment).length === 0
          ? <p className="meta">Python, platform, git state and installed packages match.</p>
          : (
            <pre className="overflow-x-auto font-mono text-[12px] text-ink-soft">
              {JSON.stringify(c.environment, null, 2)}
            </pre>
          )}
        <p className="meta mt-1">Snapshot A <Hash value={c.run_a.snapshot_hash} />, B <Hash value={c.run_b.snapshot_hash} /></p>
      </Section>
    </div>
  );
}
