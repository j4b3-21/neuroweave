import { useQuery } from "@tanstack/react-query";
import { GitCompareArrows } from "lucide-react";
import { useEffect, useState } from "react";

import { api, isActive } from "../../api/client";
import { EmptyState, ErrorText, StatusBadge } from "../../components/common";
import { formatDuration, formatTime, runDuration } from "../../lib/format";
import { useUi } from "../../state/ui";
import { Compare } from "./Compare";
import { RunDetail } from "./RunDetail";

export function RunsView() {
  const { runId, openRun, compareIds, toggleCompare } = useUi();
  const [workflowFilter, setWorkflowFilter] = useState("");
  const [comparing, setComparing] = useState<[string, string] | null>(null);
  useEffect(() => setComparing(null), [runId]);
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: api.workflows });
  const runs = useQuery({
    queryKey: ["runs", "all"],
    queryFn: () => api.runs(),
    refetchInterval: (q) => (q.state.data?.some((r) => isActive(r.status)) ? 1000 : 5000),
  });
  const visible = (runs.data ?? []).filter((r) => !workflowFilter || r.workflow_id === workflowFilter);

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-[480px] shrink-0 flex-col border-r border-rule">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-rule bg-panel px-4">
          <h1 className="text-[15px] font-semibold">Runs</h1>
          <select className="field ml-auto w-40" value={workflowFilter} aria-label="Filter by workflow"
                  onChange={(e) => setWorkflowFilter(e.target.value)}>
            <option value="">All workflows</option>
            {workflows.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <button type="button" className="btn" disabled={compareIds.length !== 2}
                  title={compareIds.length === 2 ? "Compare the two ticked runs"
                    : "Tick two runs to compare them"}
                  onClick={() => setComparing([compareIds[0]!, compareIds[1]!])}>
            <GitCompareArrows size={14} /> Compare{compareIds.length ? ` (${compareIds.length}/2)` : ""}
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto bg-panel">
          {runs.error && <div className="p-4"><ErrorText error={runs.error} /></div>}
          {runs.data && visible.length === 0 && (
            <EmptyState title="No runs yet">Run a workflow from the editor or with <code>nw run</code>.</EmptyState>
          )}
          <table className="data-table">
            <tbody>
              {visible.map((run) => {
                const selected = !comparing && run.id === runId;
                return (
                  <tr key={run.id} onClick={() => { setComparing(null); openRun(run.id); }}
                      className={`cursor-pointer ${selected ? "bg-signal-soft" : "hover:bg-rule-soft"}`}>
                    <td className="w-8" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={compareIds.includes(run.id)}
                             onChange={() => toggleCompare(run.id)}
                             aria-label={`Select run ${run.id} for comparison`} />
                    </td>
                    <td>
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium">{run.workflow_name}</span>
                        <StatusBadge status={run.status} />
                      </div>
                      <div className="flex justify-between gap-2 text-[12px] text-ink-faint">
                        <span className="font-mono">{run.id.replace(/^run_/, "")}</span>
                        <span>
                          {run.trigger}, 
                          seed {run.seed}{run.use_cache ? "" : ", no cache"},{" "}
                          {formatDuration(runDuration(run.started_at, run.finished_at))}, {formatTime(run.created_at)}
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        {comparing ? <Compare a={comparing[0]} b={comparing[1]} onClose={() => setComparing(null)} />
          : runId ? <RunDetail key={runId} runId={runId} />
          : <EmptyState title="Select a run">
              Pick a run to inspect its nodes, metrics, outputs and environment, or tick two runs to
              compare them.
            </EmptyState>}
      </div>
    </div>
  );
}
