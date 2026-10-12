import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FileText, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type {
  Issue, NodeDefinition, NodeExecutionDetail, RunRecord, ValidationReport, Workflow,
} from "../../api/types";
import { Hash, KeyValue, Section, StatusBadge } from "../../components/common";
import { formatDuration, formatNodeError, formatValue } from "../../lib/format";
import { edgeKey, parseEdgeKey, removeEdges, removeNodes, setParam, typeLabel, updateNode }
  from "../../lib/graph";
import { useUi } from "../../state/ui";
import { ParamField } from "./ParamField";

interface Props {
  draft: Workflow;
  definitions: Map<string, NodeDefinition>;
  validation: ValidationReport | null;
  latestRun: RunRecord | undefined;
  executions: Map<string, NodeExecutionDetail>;
  update: (edit: (workflow: Workflow) => Workflow) => void;
}

function IssueList({ issues }: { issues: Issue[] }) {
  if (!issues.length) return null;
  return (
    <ul className="flex flex-col gap-1">
      {issues.map((issue, i) => (
        <li key={i} className={`text-[12px] ${issue.severity === "error" ? "text-fail" : "text-busy"}`}>
          {issue.message}
        </li>
      ))}
    </ul>
  );
}

function BlurInput({ value, onCommit, label, placeholder, multiline = false }: {
  value: string;
  onCommit: (value: string) => void;
  label: string;
  placeholder?: string;
  multiline?: boolean;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const props = {
    className: "field", value: text, placeholder, "aria-label": label,
    onChange: (e: { target: { value: string } }) => setText(e.target.value),
    onBlur: () => { if (text !== value) onCommit(text); },
  };
  return multiline ? <textarea rows={3} {...props} />
    : <input {...props} onKeyDown={(e) => { if (e.key === "Enter") props.onBlur(); }} />;
}

function WorkflowPanel({ draft, validation, update }: Props) {
  const queryClient = useQueryClient();
  const { openWorkflow, toast } = useUi();
  const remove = useMutation({
    mutationFn: () => api.deleteWorkflow(draft.id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["workflow", draft.id] });
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      openWorkflow(null);
      toast(`Deleted workflow '${draft.name}'. Its runs and artifacts are kept.`, "info");
    },
    onError: (error) => toast(error.message),
  });
  const errors = validation?.issues.filter((i) => i.severity === "error").length ?? 0;
  const warnings = (validation?.issues.length ?? 0) - errors;
  return (
    <>
      <Section title="Workflow">
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1 text-[13px]">
            <span className="font-medium">Name</span>
            <BlurInput label="Workflow name" value={draft.name}
                       onCommit={(name) => update((w) => ({ ...w, name: name.trim() || w.name }))} />
          </label>
          <label className="flex flex-col gap-1 text-[13px]">
            <span className="font-medium">Description</span>
            <BlurInput label="Workflow description" multiline value={draft.description}
                       placeholder="What question does this workflow answer?"
                       onCommit={(description) => update((w) => ({ ...w, description }))} />
          </label>
          <KeyValue rows={[
            ["Id", <span className="hash">{draft.id}</span>],
            ["Nodes", draft.nodes.length],
            ["Connections", draft.edges.length],
            ["Validation", validation === null ? "checking…"
              : validation.valid
                ? <span className="text-ok">valid{warnings ? `, ${warnings} warning(s)` : ""}</span>
                : <span className="text-fail">{errors} error(s)</span>],
          ]} />
        </div>
      </Section>
      <Section title="Danger zone">
        <button type="button" className="btn btn-danger" disabled={remove.isPending}
                onClick={() => {
                  if (window.confirm(`Delete workflow '${draft.name}'? Recorded runs, snapshots and `
                    + "artifacts are not deleted.")) remove.mutate();
                }}>
          <Trash2 size={14} /> Delete workflow
        </button>
      </Section>
    </>
  );
}

function NodePanel({ nodeId, ...props }: Props & { nodeId: string }) {
  const { draft, definitions, validation, latestRun, executions, update } = props;
  const { select, openArtifact, showBottom } = useUi();
  const instance = draft.nodes.find((n) => n.id === nodeId);
  if (!instance) return null;
  const definition = definitions.get(instance.type);
  const incoming = new Map(draft.edges.filter((e) => e.target === nodeId).map((e) => [e.target_port, e]));
  const issues = validation?.issues.filter((i) => i.node_id === nodeId) ?? [];
  const detail = executions.get(nodeId);
  const execution = detail?.execution;

  return (
    <>
      <Section title="Node" actions={
        <button type="button" className="btn btn-quiet btn-danger" title="Remove node (Delete)"
                onClick={() => {
                  update((w) => removeNodes(w, new Set([nodeId])));
                  select(null);
                }}>
          <Trash2 size={14} /> Remove
        </button>}>
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1 text-[13px]">
            <span className="font-medium">Label</span>
            <BlurInput label="Node label" value={instance.label ?? ""}
                       placeholder={definition?.label ?? instance.id}
                       onCommit={(label) => update((w) => updateNode(w, nodeId,
                         { label: label.trim() || null }))} />
          </label>
          <KeyValue rows={[
            ["Instance id", <span className="hash">{instance.id}</span>],
            ["Type", <span className="hash break-all">{instance.type}</span>],
            ["Version", definition?.version ?? "—"],
            ["Code hash", <Hash value={definition?.code_hash} />],
            ["Caching", definition ? (definition.cache ? "enabled" : "disabled for this node") : "—"],
          ]} />
          {definition?.description && <p className="text-[13px] text-ink-soft">{definition.description}</p>}
          <IssueList issues={issues} />
        </div>
      </Section>

      {definition && definition.inputs.length > 0 && (
        <Section title="Inputs">
          <div className="flex flex-col gap-3">
            {definition.inputs.map((port) => {
              const edge = incoming.get(port.name);
              if (edge) {
                return (
                  <div key={port.name} className="flex flex-col gap-0.5">
                    <div className="flex items-baseline justify-between">
                      <span className="text-[13px] font-medium">{port.name}</span>
                      <span className="font-mono text-[11px] text-ink-faint">{typeLabel(port.type)}</span>
                    </div>
                    <button type="button" className="text-left text-[12px] text-signal hover:underline"
                            onClick={() => select({ kind: "edge", key: edgeKey(edge) })}>
                      connected from {edge.source}.{edge.source_port}
                    </button>
                  </div>
                );
              }
              if (port.editable) {
                return (
                  <ParamField key={port.name} port={port} value={instance.params[port.name]}
                              onChange={(value) => update((w) => setParam(w, nodeId, port.name, value))} />
                );
              }
              return (
                <div key={port.name} className="flex flex-col gap-0.5">
                  <div className="flex items-baseline justify-between">
                    <span className="text-[13px] font-medium">{port.name}</span>
                    <span className="font-mono text-[11px] text-ink-faint">{typeLabel(port.type)}</span>
                  </div>
                  <span className={`text-[12px] ${port.required ? "text-fail" : "text-ink-faint"}`}>
                    {port.required ? "Must be connected to an upstream output."
                      : `Not connected; uses default ${port.default_repr ?? ""}`}
                  </span>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {definition && (
        <Section title="Outputs">
          <ul className="flex flex-col gap-1 text-[13px]">
            {definition.outputs.map((port) => (
              <li key={port.name} className="flex justify-between gap-2">
                <span>{port.name}</span>
                <span className="font-mono text-[11px] text-ink-faint">{typeLabel(port.type)}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Last run" actions={execution && (
        <button type="button" className="btn btn-quiet" onClick={() => showBottom("logs")}>
          <FileText size={14} /> Logs
        </button>)}>
        {!latestRun || !execution ? (
          <p className="meta">This node has not run in the latest run of this workflow.</p>
        ) : (
          <div className="flex flex-col gap-2">
            <KeyValue rows={[
              ["Status", <StatusBadge status={execution.status} cacheHit={execution.cache_hit} />],
              ["Duration", formatDuration(execution.duration_ms)],
              ["Seed", execution.seed ?? "—"],
              ["Cache", execution.cache_note ?? "—"],
              ["Params used", Object.keys(execution.params).length
                ? <span className="font-mono text-[12px]">
                    {Object.entries(execution.params).map(([k, v]) => `${k}=${formatValue(v)}`).join(", ")}
                  </span>
                : "—"],
            ]} />
            {execution.error && (
              <p className="rounded-md bg-fail/5 px-2 py-1.5 text-[12px] text-fail">
                {formatNodeError(execution.error, execution.error_type)}
              </p>
            )}
            {detail.outputs.length > 0 && (
              <ul className="flex flex-col gap-1">
                {detail.outputs.map((artifact) => (
                  <li key={artifact.id}>
                    <button type="button" onClick={() => openArtifact(artifact.id)}
                            className="flex w-full items-center justify-between gap-2 rounded-md border border-rule px-2 py-1 text-left text-[12px] hover:border-signal">
                      <span>{artifact.port} <span className="text-ink-faint">({artifact.kind})</span></span>
                      <ArrowRight size={13} className="text-ink-faint" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Section>
    </>
  );
}

function EdgePanel({ edgeId, draft, definitions, validation, update }: Props & { edgeId: string }) {
  const select = useUi((s) => s.select);
  const edge = parseEdgeKey(edgeId);
  if (!edge) return null;
  const source = draft.nodes.find((n) => n.id === edge.source);
  const target = draft.nodes.find((n) => n.id === edge.target);
  const out = source && definitions.get(source.type)?.outputs.find((p) => p.name === edge.source_port);
  const inp = target && definitions.get(target.type)?.inputs.find((p) => p.name === edge.target_port);
  const issues = validation?.issues.filter((i) => i.edge && edgeKey(i.edge) === edgeId) ?? [];
  return (
    <Section title="Connection" actions={
      <button type="button" className="btn btn-quiet btn-danger"
              onClick={() => { update((w) => removeEdges(w, new Set([edgeId]))); select(null); }}>
        <Trash2 size={14} /> Remove
      </button>}>
      <div className="flex flex-col gap-2">
        <KeyValue rows={[
          ["From", <span className="font-mono text-[12px]">{edge.source}.{edge.source_port}</span>],
          ["Produces", out ? <span className="font-mono text-[12px]">{typeLabel(out.type)}</span> : "—"],
          ["To", <span className="font-mono text-[12px]">{edge.target}.{edge.target_port}</span>],
          ["Accepts", inp ? <span className="font-mono text-[12px]">{typeLabel(inp.type)}</span> : "—"],
        ]} />
        {issues.length ? <IssueList issues={issues} />
          : <p className="text-[12px] text-ok">Types are compatible.</p>}
      </div>
    </Section>
  );
}

export function Inspector(props: Props) {
  const selection = useUi((s) => s.selection);
  return (
    <aside className="w-80 shrink-0 overflow-y-auto border-l border-rule bg-panel" aria-label="Inspector">
      {selection?.kind === "node" ? <NodePanel nodeId={selection.id} {...props} />
        : selection?.kind === "edge" ? <EdgePanel edgeId={selection.key} {...props} />
        : <WorkflowPanel {...props} />}
    </aside>
  );
}
