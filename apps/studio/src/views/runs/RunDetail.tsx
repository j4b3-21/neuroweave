import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, RotateCcw, Square } from "lucide-react";
import { useState, type ReactNode } from "react";

import { api, isActive } from "../../api/client";
import type { Environment, ReproductionReport, RunDetail as RunDetailData } from "../../api/types";
import { EmptyState, ErrorText, Hash, KeyValue, Section, StatusBadge } from "../../components/common";
import { environmentBadge } from "../../lib/environment";
import {
  formatDuration, formatNodeError, formatNumber, formatTime, formatValue, runDuration,
} from "../../lib/format";
import { useUi } from "../../state/ui";

const VERDICT_TEXT: Record<ReproductionReport["verdict"], { tone: string; text: string }> = {
  reproduced: { tone: "text-ok", text: "Reproduced: the re-execution produced byte-identical outputs "
    + "(equal SHA-256) for every output of the original run." },
  not_reproduced: { tone: "text-fail", text: "Not reproduced: at least one output of the re-execution is "
    + "missing or differs." },
  failed: { tone: "text-fail", text: "The reproduction run did not succeed." },
  pending: { tone: "text-busy", text: "The reproduction is still running." },
};

function ReproductionPanel({ runId, status }: { runId: string; status: string }) {
  const report = useQuery({
    queryKey: ["reproduction", runId, status],
    queryFn: () => api.reproduction(runId),
  });
  const openRun = useUi((s) => s.openRun);
  if (report.error) return <ErrorText error={report.error} />;
  if (!report.data) return <p className="meta">Loading verdict…</p>;
  const r = report.data;
  const verdict = VERDICT_TEXT[r.verdict];
  const env = environmentBadge(r.environment_match, r.isolated);
  const differing = r.outputs.filter((o) => !o.identical);
  return (
    <div className="flex flex-col gap-2">
      <p className={`text-[13px] font-medium ${verdict.tone}`}>{verdict.text}</p>
      <p className={`text-[12px] font-medium ${env.tone}`} title={env.title} data-tour="env-badge">
        {env.label}
      </p>
      <KeyValue rows={[
        ["Original run", <button type="button" className="font-mono text-[12px] text-signal hover:underline"
                                 onClick={() => openRun(r.original_run_id)}>{r.original_run_id}</button>],
        ["Policy", <span title="Outputs must have identical SHA-256 content hashes">{r.policy}</span>],
        ["Outputs compared", `${r.outputs.length} (${differing.length} differ)`],
        ["Environment", <span title={env.title}>{env.label}</span>],
      ]} />
      {differing.length > 0 && (
        <table className="data-table">
          <thead><tr><th>Output</th><th>Original</th><th>Reproduced</th></tr></thead>
          <tbody>
            {differing.map((o) => (
              <tr key={`${o.node_id}.${o.port}`}>
                <td className="font-mono text-[12px]">{o.node_id}.{o.port}</td>
                <td><Hash value={o.original} /></td>
                <td><Hash value={o.reproduced} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {r.notes.length > 0 && (
        <ul className="list-disc pl-5 text-[12px] text-ink-soft">
          {r.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      )}
      <p className="meta">
        {r.isolated
          ? "The snapshot was re-executed in a fresh virtual environment rebuilt from the "
            + "original run's lock (same OS and architecture required). System libraries are "
            + "not rebuilt."
          : "The snapshot was re-executed on this machine with the same seed, without the cache, "
            + "using the code and packages installed now. Use “Reproduce in a rebuilt environment” "
            + "to rebuild the original package set with uv first."}
      </p>
    </div>
  );
}

function EnvironmentPanel({ environment }: { environment: Environment | null }) {
  const [showPackages, setShowPackages] = useState(false);
  if (!environment) return <p className="meta">Not captured (the run has not started).</p>;
  const packages = Object.entries(environment.packages ?? {});
  const git = environment.git;
  return (
    <div className="flex flex-col gap-2">
      <KeyValue rows={[
        ["Python", environment.python
          ? `${environment.python.implementation} ${environment.python.version}` : "—"],
        ["Platform", environment.platform
          ? `${environment.platform.system} ${environment.platform.release} (${environment.platform.machine})`
          : "—"],
        ["NeuroWeave", environment.neuroweave ?? "—"],
        ["Git", git ? <span><Hash value={git.commit} /> {git.branch ?? "detached"}
          {git.dirty && <span className="text-busy"> with uncommitted changes</span>}</span>
          : "not a git repository"],
        ["Lock", environment.lock
          ? <Hash value={environment.lock.hash} length={16} />
          : "not recorded"],
        ["Packages", <button type="button" className="text-signal hover:underline"
                             onClick={() => setShowPackages(!showPackages)}>
          {packages.length} installed {showPackages ? "(hide)" : "(show)"}</button>],
      ]} />
      {showPackages && (
        <div className="max-h-48 overflow-y-auto rounded-md border border-rule-soft font-mono text-[12px]">
          {packages.map(([name, version]) => (
            <div key={name} className="flex justify-between border-b border-rule-soft px-2 py-0.5 last:border-0">
              <span>{name}</span><span className="text-ink-faint">{version}</span>
            </div>
          ))}
        </div>
      )}
      <p className="meta">Environment variables are not recorded, so secrets never enter run records.
        Use <span className="font-mono">nw env show</span> to export the pinned lock.</p>
    </div>
  );
}

function NodesTable({ detail }: { detail: RunDetailData }) {
  const openArtifact = useUi((s) => s.openArtifact);
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <table className="data-table">
      <thead>
        <tr><th>#</th><th>Node</th><th>Status</th><th>Duration</th><th>Outputs</th></tr>
      </thead>
      <tbody>
        {detail.nodes.map(({ execution, outputs }) => (
          <tr key={execution.id}>
            <td className="text-ink-faint">{execution.ordinal + 1}</td>
            <td>
              <button type="button" className="text-left font-mono text-[12px] hover:text-signal"
                      onClick={() => setExpanded(expanded === execution.id ? null : execution.id)}>
                {execution.node_id}
              </button>
              {expanded === execution.id && (
                <div className="mt-1 flex flex-col gap-1 text-[12px] text-ink-soft">
                  <span>version {execution.definition_version ?? "—"}, code <Hash value={execution.code_hash} /></span>
                  <span>seed {execution.seed ?? "—"}</span>
                  <span>{execution.cache_note}</span>
                  {Object.keys(execution.params).length > 0 && (
                    <span className="font-mono">
                      {Object.entries(execution.params).map(([k, v]) => `${k}=${formatValue(v)}`).join(", ")}
                    </span>
                  )}
                </div>
              )}
              {execution.error && (
                <details className="mt-1 text-[12px] text-fail">
                  <summary className="cursor-pointer">{formatNodeError(execution.error, execution.error_type)}</summary>
                  <pre className="mt-1 overflow-x-auto font-mono text-[11px] whitespace-pre-wrap">{execution.traceback}</pre>
                </details>
              )}
            </td>
            <td><StatusBadge status={execution.status} cacheHit={execution.cache_hit} /></td>
            <td>{formatDuration(execution.duration_ms)}</td>
            <td>
              <div className="flex flex-wrap gap-1">
                {outputs.map((artifact) => (
                  <button key={artifact.id} type="button" onClick={() => openArtifact(artifact.id)}
                          title={`${artifact.kind}, ${artifact.content_hash}`}
                          className="rounded border border-rule px-1.5 text-[12px] hover:border-signal hover:text-signal">
                    {artifact.port}
                  </button>
                ))}
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RunDetail({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const { openRun, openWorkflow, toast } = useUi();
  const detail = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (q) => (isActive(q.state.data?.run.status) ? 800 : false),
  });
  const allRuns = useQuery({ queryKey: ["runs", "all"], queryFn: () => api.runs() });
  const reproductions = (allRuns.data ?? []).filter((r) => r.reproduces_run_id === runId);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["runs"] });
    void queryClient.invalidateQueries({ queryKey: ["run", runId] });
  };
  const reproduce = useMutation({
    mutationFn: (opts: { isolated?: boolean } = {}) => api.reproduce(runId, opts),
    onSuccess: (run, opts) => {
      invalidate();
      toast(opts.isolated
        ? "Rebuilding the original environment with uv, then reproducing inside it."
        : "Reproduction started with the original snapshot and seed, without the cache.",
      "info");
      openRun(run.id);
    },
    onError: (error) => toast(error.message),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelRun(runId),
    onSuccess: invalidate,
    onError: (error) => toast(error.message),
  });
  const restore = useMutation({
    mutationFn: () => api.saveWorkflow(detail.data!.workflow),
    onSuccess: ({ workflow, revision }) => {
      queryClient.setQueryData(["workflow", workflow.id], { workflow, revision });
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      toast(`Workflow '${workflow.name}' restored to the version used by this run.`, "info");
      openWorkflow(workflow.id);
    },
    onError: (error) => toast(error.message),
  });

  if (detail.error) return <EmptyState title="Run not found"><ErrorText error={detail.error} /></EmptyState>;
  if (!detail.data) return <p className="meta p-6">Loading run…</p>;
  const { run, workflow, metrics } = detail.data;
  const active = isActive(run.status);
  const busy = reproduce.isPending || run.status === "CANCELLED";

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-panel">
      <header className="flex items-center gap-3 border-b border-rule px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h2 className="text-[15px] font-semibold">{run.workflow_name}</h2>
            <StatusBadge status={run.status} />
          </div>
          <div className="hash">{run.id}</div>
        </div>
        <div className="ml-auto flex flex-wrap justify-end gap-2">
          {active ? (
            <button type="button" className="btn btn-danger" onClick={() => cancel.mutate()}
                    disabled={cancel.isPending || run.cancel_requested}>
              <Square size={13} /> {run.cancel_requested ? "Cancelling…" : "Cancel"}
            </button>
          ) : (
            <>
              <button type="button" className="btn" data-tour="reproduce"
                      onClick={() => reproduce.mutate({})}
                      disabled={busy}
                      title="Re-execute this exact snapshot with the same seed, ignoring the cache, and compare output hashes">
                <RotateCcw size={13} /> Reproduce
              </button>
              <button type="button" className="btn" data-tour="reproduce-isolated"
                      onClick={() => reproduce.mutate({ isolated: true })}
                      disabled={busy || !run.environment?.lock}
                      title={run.environment?.lock
                        ? "Rebuild a fresh virtual environment from this run's lock with uv, then reproduce inside it"
                        : "This run has no environment lock; re-run it with a current NeuroWeave first"}>
                <RotateCcw size={13} /> Reproduce in a rebuilt environment
              </button>
            </>
          )}
          <button type="button" className="btn" disabled={restore.isPending}
                  title="Replace the current workflow with the version this run executed"
                  onClick={() => {
                    if (window.confirm(`Replace the current '${workflow.name}' workflow with the version `
                      + "this run executed?\n\nThe current version can only be recovered later if it "
                      + "was itself run, because each run keeps a snapshot of what it executed.")) {
                      restore.mutate();
                    }
                  }}>
            <History size={13} /> Restore this version
          </button>
        </div>
      </header>

      <Section title="Overview">
        <KeyValue rows={[
          ["Workflow", <button type="button" className="text-signal hover:underline"
                               onClick={() => openWorkflow(run.workflow_id)}>{run.workflow_id}</button>],
          ["Snapshot", <Hash value={run.snapshot_hash} length={16} />],
          ["Seed", run.seed],
          ["Cache", run.use_cache ? "reuse allowed" : "disabled (every node executed)"],
          ["Trigger", run.trigger],
          ["Created", formatTime(run.created_at)],
          ["Duration", formatDuration(runDuration(run.started_at, run.finished_at))],
          ...(run.reproduces_run_id ? [["Reproduces", (
            <button type="button" className="font-mono text-[12px] text-signal hover:underline"
                    onClick={() => openRun(run.reproduces_run_id)}>{run.reproduces_run_id}</button>
          )] as [string, ReactNode]] : []),
        ]} />
        {run.error && <p className="mt-2 rounded-md bg-fail/5 px-2 py-1.5 text-[13px] text-fail">{run.error}</p>}
      </Section>

      {run.reproduces_run_id && (
        <Section title="Reproduction verdict">
          <ReproductionPanel runId={run.id} status={run.status} />
        </Section>
      )}
      {reproductions.length > 0 && (
        <Section title="Reproductions of this run">
          <ul className="flex flex-col gap-1">
            {reproductions.map((r) => (
              <li key={r.id} className="flex items-center gap-3 text-[13px]">
                <StatusBadge status={r.status} />
                <button type="button" className="font-mono text-[12px] text-signal hover:underline"
                        onClick={() => openRun(r.id)}>{r.id}</button>
                <span className="meta">{formatTime(r.created_at)}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title={`Nodes (${detail.data.nodes.length})`}>
        <NodesTable detail={detail.data} />
      </Section>

      <Section title="Metrics">
        {metrics.length === 0 ? <p className="meta">No metrics were logged.</p> : (
          <table className="data-table">
            <thead><tr><th>Node</th><th>Metric</th><th>Value</th><th>Step</th><th>Goal</th></tr></thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={`${m.node_execution_id}.${m.name}.${m.step ?? ""}.${m.id}`}>
                  <td className="font-mono text-[12px]">{m.node_id}</td>
                  <td>{m.name}</td>
                  <td className="font-mono">{formatNumber(m.value)}</td>
                  <td>{m.step ?? "—"}</td>
                  <td className="text-ink-faint">{m.direction ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Environment">
        <EnvironmentPanel environment={run.environment} />
      </Section>
    </div>
  );
}
