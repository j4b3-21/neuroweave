import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp } from "lucide-react";

import { api, isActive } from "../../api/client";
import type { RunDetail, ValidationReport } from "../../api/types";
import { StatusBadge } from "../../components/common";
import { formatDuration, formatNodeError } from "../../lib/format";
import { useUi, type BottomTab } from "../../state/ui";

function Problems({ validation }: { validation: ValidationReport | null }) {
  const select = useUi((s) => s.select);
  if (!validation) return <p className="meta p-3">Validating…</p>;
  if (!validation.issues.length) {
    return <p className="p-3 text-[13px] text-ok">No problems. The workflow is ready to run.</p>;
  }
  return (
    <table className="data-table">
      <tbody>
        {validation.issues.map((issue, i) => (
          <tr key={i} className="cursor-pointer hover:bg-rule-soft"
              onClick={() => issue.node_id && select({ kind: "node", id: issue.node_id })}>
            <td className={`w-20 font-medium ${issue.severity === "error" ? "text-fail" : "text-busy"}`}>
              {issue.severity}
            </td>
            <td className="w-40 font-mono text-[12px]">{issue.node_id ?? "workflow"}</td>
            <td>{issue.message}</td>
            <td className="w-36 font-mono text-[11px] text-ink-faint">{issue.code}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RunProgress({ detail }: { detail: RunDetail | undefined }) {
  const { select, openRun } = useUi();
  if (!detail) return <p className="meta p-3">This workflow has not been run yet.</p>;
  const { run, nodes } = detail;
  return (
    <div>
      <div className="flex items-center gap-3 border-b border-rule-soft px-3 py-1.5 text-[12px]">
        <StatusBadge status={run.status} />
        <span className="font-mono text-ink-soft">{run.id}</span>
        <span className="text-ink-faint">seed {run.seed}{run.use_cache ? "" : ", cache off"}</span>
        <button type="button" className="ml-auto text-signal hover:underline" onClick={() => openRun(run.id)}>
          Open run details
        </button>
      </div>
      {run.error && <p className="px-3 py-1.5 text-[12px] text-fail">{run.error}</p>}
      <table className="data-table">
        <tbody>
          {nodes.map(({ execution }) => (
            <tr key={execution.id} className="cursor-pointer hover:bg-rule-soft"
                onClick={() => select({ kind: "node", id: execution.node_id })}>
              <td className="w-8 text-ink-faint">{execution.ordinal + 1}</td>
              <td className="w-44 font-mono text-[12px]">{execution.node_id}</td>
              <td className="w-28"><StatusBadge status={execution.status} cacheHit={execution.cache_hit} /></td>
              <td className="w-20">{formatDuration(execution.duration_ms)}</td>
              <td className={execution.error ? "text-fail" : "text-ink-faint"}>
                {execution.error ? formatNodeError(execution.error, execution.error_type) : execution.cache_note}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Logs({ detail }: { detail: RunDetail | undefined }) {
  const selection = useUi((s) => s.selection);
  const nodeId = selection?.kind === "node" ? selection.id : null;
  const execution = detail?.nodes.find((n) => n.execution.node_id === nodeId)?.execution;
  const logs = useQuery({
    queryKey: ["logs", detail?.run.id, nodeId],
    queryFn: () => api.logs(detail!.run.id, nodeId!),
    enabled: Boolean(detail && execution),
    refetchInterval: isActive(execution?.status) ? 1000 : false,
  });
  if (!nodeId) return <p className="meta p-3">Select a node to see its log from the latest run.</p>;
  if (!execution) return <p className="meta p-3">Node '{nodeId}' was not part of the latest run.</p>;
  return (
    <div className="p-3">
      {execution.traceback && (
        <pre className="mb-2 overflow-x-auto rounded-md bg-fail/5 p-2 font-mono text-[12px] text-fail">
          {execution.traceback}
        </pre>
      )}
      <pre className="overflow-x-auto font-mono text-[12px] whitespace-pre-wrap text-ink-soft">
        {logs.isPending ? "Loading…" : logs.data || (execution.cache_hit
          ? "Reused from cache; the node did not execute, so there is no log for this run."
          : "(no output)")}
      </pre>
    </div>
  );
}

export function BottomPanel({ validation, detail }: {
  validation: ValidationReport | null;
  detail: RunDetail | undefined;
}) {
  const { bottomOpen, bottomTab, showBottom, setBottomOpen } = useUi();
  const problemCount = validation?.issues.length ?? 0;
  const tabs: [BottomTab, string][] = [
    ["problems", `Problems${problemCount ? ` (${problemCount})` : ""}`],
    ["run", "Latest run"],
    ["logs", "Logs"],
  ];
  return (
    <div className="flex shrink-0 flex-col border-t border-rule bg-panel" data-tour="bottom">
      <div className="flex h-8 items-center gap-1 px-2" role="tablist">
        {tabs.map(([tab, label]) => (
          <button key={tab} type="button" role="tab" aria-selected={bottomOpen && bottomTab === tab}
                  onClick={() => (bottomOpen && bottomTab === tab ? setBottomOpen(false) : showBottom(tab))}
                  className={`rounded px-2 py-0.5 text-[12px] font-medium ${
                    bottomOpen && bottomTab === tab ? "bg-signal-soft text-signal" : "text-ink-soft hover:bg-rule-soft"
                  } ${tab === "problems" && validation && !validation.valid ? "text-fail" : ""}`}>
            {label}
          </button>
        ))}
        <button type="button" className="ml-auto text-ink-faint hover:text-ink"
                aria-label={bottomOpen ? "Collapse panel" : "Expand panel"}
                onClick={() => setBottomOpen(!bottomOpen)}>
          {bottomOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
      </div>
      {bottomOpen && (
        <div className="h-56 overflow-y-auto border-t border-rule-soft">
          {bottomTab === "problems" && <Problems validation={validation} />}
          {bottomTab === "run" && <RunProgress detail={detail} />}
          {bottomTab === "logs" && <Logs detail={detail} />}
        </div>
      )}
    </div>
  );
}
