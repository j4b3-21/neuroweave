import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  applyNodeChanges, Background, Controls, ReactFlow, ReactFlowProvider, useReactFlow,
  type Connection, type Edge as FlowEdge, type NodeChange,
} from "@xyflow/react";
import { CheckCircle2, Play, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError, isActive } from "../../api/client";
import type {
  Edge, NodeDefinition, NodeExecutionDetail, ValidationReport, Workflow,
} from "../../api/types";
import { EmptyState, ErrorText, StatusBadge } from "../../components/common";
import { formatTime } from "../../lib/format";
import { addNode, connect, edgeKey, moveNodes, parseEdgeKey, removeEdges, removeNodes }
  from "../../lib/graph";
import { useUi } from "../../state/ui";
import { BottomPanel } from "./BottomPanel";
import { Inspector } from "./Inspector";
import { NodeCard, type NodeCardNode } from "./NodeCard";
import { DRAG_MIME, Palette } from "./Palette";
import { useWorkflowDraft, type SaveState } from "./useWorkflowDraft";

const nodeTypes = { nwNode: NodeCard };

/** Structure that determines what a run computes (layout and labels excluded). */
const semantics = (w: Workflow) => JSON.stringify({
  nodes: [...w.nodes].sort((a, b) => a.id.localeCompare(b.id)).map((n) => [n.id, n.type, n.params]),
  edges: w.edges.map(edgeKey).sort(),
});

const SAVE_LABEL: Record<SaveState, string> = {
  idle: "Saved", dirty: "Unsaved changes", saving: "Saving…", saved: "Saved", error: "Save failed",
  conflict: "Changed elsewhere",
};

function Editor({ workflowId }: { workflowId: string }) {
  const queryClient = useQueryClient();
  const { selection, select, showBottom, toast, openRun } = useUi();
  const { screenToFlowPosition } = useReactFlow();
  const canvasRef = useRef<HTMLDivElement>(null);
  const [seed, setSeed] = useState("");
  const [useCache, setUseCache] = useState(true);

  const project = useQuery({ queryKey: ["project"], queryFn: api.project });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.catalog() });
  const definitions = useMemo(
    () => new Map((catalog.data?.definitions ?? []).map((d) => [d.id, d])), [catalog.data]);
  const { draft, validation, setValidation, saveState, saveError, update, flush, reload, loadError } =
    useWorkflowDraft(workflowId);

  const runs = useQuery({
    queryKey: ["runs", workflowId],
    queryFn: () => api.runs(workflowId),
    refetchInterval: (q) => (isActive(q.state.data?.[0]?.status) ? 1000 : 5000),
  });
  const latestRun = runs.data?.[0];
  const detail = useQuery({
    queryKey: ["run", latestRun?.id],
    queryFn: () => api.run(latestRun!.id),
    enabled: Boolean(latestRun),
    refetchInterval: (q) => (isActive(q.state.data?.run.status) ? 800 : false),
  });
  const running = isActive(latestRun?.status) || isActive(detail.data?.run.status);

  const executions = useMemo(
    () => new Map<string, NodeExecutionDetail>(
      (detail.data?.nodes ?? []).map((n) => [n.execution.node_id, n])),
    [detail.data]);
  const stale = Boolean(draft && detail.data && semantics(draft) !== semantics(detail.data.workflow));

  const errorsByNode = useMemo(() => {
    const counts = new Map<string, number>();
    for (const issue of validation?.issues ?? []) {
      if (issue.severity === "error" && issue.node_id) {
        counts.set(issue.node_id, (counts.get(issue.node_id) ?? 0) + 1);
      }
    }
    return counts;
  }, [validation]);
  const invalidEdges = useMemo(() => new Set((validation?.issues ?? [])
    .filter((i) => i.severity === "error" && i.edge).map((i) => edgeKey(i.edge!))), [validation]);

  const [flowNodes, setFlowNodes] = useState<NodeCardNode[]>([]);
  useEffect(() => {
    if (!draft) return;
    setFlowNodes((previous) => {
      const byId = new Map(previous.map((n) => [n.id, n]));
      return draft.nodes.map((instance): NodeCardNode => {
        const old = byId.get(instance.id);
        return {
          id: instance.id,
          type: "nwNode",
          ariaLabel: `Node ${instance.id}`,
          position: old?.dragging ? old.position : instance.position,
          dragging: old?.dragging,
          measured: old?.measured,
          selected: selection?.kind === "node" && selection.id === instance.id,
          data: {
            instance,
            definition: definitions.get(instance.type),
            connectedInputs: new Set(draft.edges.filter((e) => e.target === instance.id)
              .map((e) => e.target_port)),
            execution: executions.get(instance.id)?.execution,
            errorCount: errorsByNode.get(instance.id) ?? 0,
            stale,
          },
        };
      });
    });
  }, [draft, definitions, executions, errorsByNode, selection, stale]);

  const flowEdges = useMemo<FlowEdge[]>(() => (draft?.edges ?? []).map((e) => {
    const key = edgeKey(e);
    const sourceStatus = executions.get(e.source)?.execution.status;
    return {
      id: key, source: e.source, sourceHandle: e.source_port, target: e.target,
      targetHandle: e.target_port,
      ariaLabel: `Connection ${key}`,
      selected: selection?.kind === "edge" && selection.key === key,
      className: invalidEdges.has(key) ? "nw-invalid" : undefined,
      animated: running && sourceStatus === "SUCCEEDED"
        && isActive(executions.get(e.target)?.execution.status),
    };
  }), [draft, selection, invalidEdges, executions, running]);

  const onNodesChange = useCallback((changes: NodeChange<NodeCardNode>[]) => {
    setFlowNodes((nodes) => applyNodeChanges(changes, nodes));
  }, []);

  const onConnect = useCallback((connection: Connection) => {
    if (!draft || !connection.sourceHandle || !connection.targetHandle) return;
    const edge: Edge = {
      source: connection.source, source_port: connection.sourceHandle,
      target: connection.target, target_port: connection.targetHandle,
    };
    const result = connect(draft, edge);
    if ("error" in result) return toast(result.error);
    api.validate(result.workflow).then((report) => {
      const key = edgeKey(edge);
      const rejected = report.issues.find((i) => i.code === "type_mismatch" && i.edge
        && edgeKey(i.edge) === key);
      if (rejected) return toast(rejected.message);
      update((w) => {
        const next = connect(w, edge);
        return "workflow" in next ? next.workflow : w;
      });
      const warning = report.issues.find((i) => i.code === "type_warning" && i.edge
        && edgeKey(i.edge) === key);
      if (warning) toast(warning.message, "info");
    }, (error: Error) => toast(`Could not check this connection: ${error.message}`));
  }, [draft, toast, update]);

  const addDefinition = useCallback((definition: NodeDefinition, at?: { x: number; y: number }) => {
    let position = at;
    if (!position) {
      const rect = canvasRef.current?.getBoundingClientRect();
      const centre = screenToFlowPosition({
        x: (rect?.left ?? 0) + (rect?.width ?? 600) / 2,
        y: (rect?.top ?? 0) + (rect?.height ?? 400) / 3,
      });
      const offset = ((draft?.nodes.length ?? 0) % 5) * 24;
      position = { x: centre.x - 105 + offset, y: centre.y + offset };
    }
    let added: string | null = null;
    update((w) => {
      const result = addNode(w, definition, Math.round(position.x), Math.round(position.y));
      added = result.nodeId;
      return result.workflow;
    });
    if (added) select({ kind: "node", id: added });
  }, [draft, screenToFlowPosition, select, update]);

  const startRun = useMutation({
    mutationFn: async () => {
      if (!(await flush())) throw new Error("The workflow could not be saved, so it was not run.");
      const parsedSeed = seed.trim() === "" ? null : Number(seed);
      if (parsedSeed !== null && !Number.isInteger(parsedSeed)) throw new Error("Seed must be an integer.");
      return api.startRun(workflowId, { seed: parsedSeed, use_cache: useCache });
    },
    onSuccess: (run) => {
      queryClient.setQueryData(["runs", workflowId], (old: typeof runs.data) => [run, ...(old ?? [])]);
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      showBottom("run");
    },
    onError: (error) => {
      const report = error instanceof ApiError
        ? (error.detail as { validation?: ValidationReport } | null)?.validation : undefined;
      if (report) {
        setValidation(report);
        showBottom("problems");
      }
      toast(error.message);
    },
  });
  const cancelRun = useMutation({
    mutationFn: () => api.cancelRun(latestRun!.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["runs", workflowId] }),
    onError: (error) => toast(error.message),
  });
  const validateNow = useMutation({
    mutationFn: async () => {
      await flush();
      return api.validate(draft!);
    },
    onSuccess: (report) => {
      setValidation(report);
      showBottom("problems");
    },
    onError: (error) => toast(error.message),
  });

  if (loadError) {
    return <EmptyState title="This workflow could not be loaded."><ErrorText error={loadError} /></EmptyState>;
  }
  if (!draft) return <p className="meta p-6">Loading workflow…</p>;

  const runBlocked = !validation ? "Validating…" : !validation.valid
    ? "Fix the problems listed below before running."
    : saveState === "error" || saveState === "conflict" ? "The latest edit is not saved." : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-rule bg-panel px-4">
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-semibold">{draft.name}</h1>
        </div>
        <span className={`text-[12px] ${saveState === "error" || saveState === "conflict"
          ? "text-fail" : "text-ink-faint"}`}
              title={saveError ?? undefined} role="status">
          {SAVE_LABEL[saveState]}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button type="button" className="btn" data-tour="validate"
                  onClick={() => validateNow.mutate()} disabled={validateNow.isPending}>
            <CheckCircle2 size={14} /> Validate
          </button>
          <div className="flex items-center gap-2" data-tour="run">
            <label className="flex items-center gap-1.5 text-[12px] text-ink-soft">
              Seed
              <input className="field w-28" inputMode="numeric" value={seed}
                     placeholder={`default ${project.data?.default_seed ?? ""}`}
                     onChange={(e) => setSeed(e.target.value)} aria-label="Run seed" />
            </label>
            <label className="flex items-center gap-1.5 text-[12px] text-ink-soft"
                   title="Reuse results of identical node executions (same code, params, inputs and seed)">
              <input type="checkbox" checked={useCache} onChange={(e) => setUseCache(e.target.checked)} />
              Reuse cached results
            </label>
            {running ? (
              <button type="button" className="btn btn-danger" onClick={() => cancelRun.mutate()}
                      disabled={cancelRun.isPending || latestRun?.cancel_requested}>
                <Square size={13} /> {latestRun?.cancel_requested ? "Cancelling…" : "Cancel run"}
              </button>
            ) : (
              <button type="button" className="btn btn-primary" title={runBlocked ?? "Run this workflow"}
                      onClick={() => startRun.mutate()} disabled={Boolean(runBlocked) || startRun.isPending}>
                <Play size={13} /> Run
              </button>
            )}
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <Palette catalog={catalog.data} onAdd={(definition) => addDefinition(definition)} />
        <div className="flex min-w-0 flex-1 flex-col">
          {(saveState === "conflict" || saveState === "error") && (
            <div className="flex shrink-0 items-center gap-3 border-b border-fail/30 bg-fail/5 px-3 py-1.5 text-[13px] text-fail"
                 role="alert">
              <span className="flex-1">
                {saveState === "conflict"
                  ? `${saveError} Reload to continue from the stored version; editing is paused until then.`
                  : `Saving failed: ${saveError}`}
              </span>
              {saveState === "conflict" ? (
                <button type="button" className="btn" onClick={() => void reload()}>Reload workflow</button>
              ) : (
                <button type="button" className="btn" onClick={() => void flush()}>Retry</button>
              )}
            </div>
          )}
          {latestRun && (
            <div className="flex h-8 shrink-0 items-center gap-3 border-b border-rule bg-panel px-3 text-[12px]">
              <span className="text-ink-faint">Latest run</span>
              <StatusBadge status={latestRun.status} />
              <span className="text-ink-faint">{formatTime(latestRun.created_at)}</span>
              {stale && !running && (
                <span className="text-busy">The workflow has changed since this run; statuses are from the old version.</span>
              )}
              <button type="button" className="ml-auto text-signal hover:underline"
                      onClick={() => openRun(latestRun.id)}>
                Run details
              </button>
            </div>
          )}
          <div ref={canvasRef} className="relative min-h-0 flex-1" data-tour="canvas"
               onDragOver={(e) => {
                 if (e.dataTransfer.types.includes(DRAG_MIME)) {
                   e.preventDefault();
                   e.dataTransfer.dropEffect = "copy";
                 }
               }}
               onDrop={(e) => {
                 const definition = definitions.get(e.dataTransfer.getData(DRAG_MIME));
                 if (!definition) return;
                 e.preventDefault();
                 const p = screenToFlowPosition({ x: e.clientX, y: e.clientY });
                 addDefinition(definition, { x: p.x - 105, y: p.y - 20 });
               }}>
            <ReactFlow<NodeCardNode, FlowEdge>
              nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onConnect={onConnect}
              onNodeClick={(_, node) => select({ kind: "node", id: node.id })}
              onEdgeClick={(_, edge) => select({ kind: "edge", key: edge.id })}
              onPaneClick={() => select(null)}
              onNodeDragStop={(_, __, nodes) => update(
                (w) => moveNodes(w, new Map(nodes.map((n) => [n.id, n.position]))))}
              onDelete={({ nodes, edges }) => {
                update((w) => removeEdges(removeNodes(w, new Set(nodes.map((n) => n.id))),
                  new Set(edges.map((e) => e.id).filter((id) => parseEdgeKey(id)))));
                select(null);
              }}
              deleteKeyCode={["Backspace", "Delete"]}
              fitView fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
              minZoom={0.2} maxZoom={2}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={20} size={1} color="#d5dce2" />
              <Controls showInteractive={false} />
            </ReactFlow>
            {draft.nodes.length === 0 && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <div className="max-w-sm rounded-md border border-dashed border-rule bg-panel/80 px-5 py-4 text-center">
                  <p className="font-medium">This workflow is empty.</p>
                  <p className="text-[13px] text-ink-soft">
                    Add nodes from the palette, then drag from an output port to an input port to connect them.
                  </p>
                </div>
              </div>
            )}
          </div>
          <BottomPanel validation={validation} detail={detail.data} />
        </div>
        <Inspector draft={draft} definitions={definitions} validation={validation}
                   latestRun={latestRun} executions={executions} update={update} />
      </div>
    </div>
  );
}

export function WorkflowView() {
  const workflowId = useUi((s) => s.workflowId);
  const openWorkflow = useUi((s) => s.openWorkflow);
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: api.workflows });
  const first = workflows.data?.[0]?.id;
  const exists = workflows.data?.some((w) => w.id === workflowId);

  useEffect(() => {
    if (workflows.data && (!workflowId || !exists) && first) openWorkflow(first);
  }, [workflows.data, workflowId, exists, first, openWorkflow]);

  if (workflows.isError) {
    return <EmptyState title="Cannot reach the NeuroWeave server."><ErrorText error={workflows.error} /></EmptyState>;
  }
  if (workflows.data && workflows.data.length === 0) {
    return (
      <EmptyState title="No workflows yet">
        <p>Create one with the + button in the sidebar, or import a workflow file from the command line:</p>
        <pre className="mt-2 rounded-md bg-panel p-2 font-mono text-[12px]">nw workflows import workflow.json</pre>
      </EmptyState>
    );
  }
  if (!workflowId || !exists) return <p className="meta p-6">Loading…</p>;
  return (
    <ReactFlowProvider key={workflowId}>
      <Editor workflowId={workflowId} />
    </ReactFlowProvider>
  );
}
