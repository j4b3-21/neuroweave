import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, FlaskConical, FolderCog, Package, Plus, Workflow as WorkflowIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { api } from "../api/client";
import { useUi, type View } from "../state/ui";
import { statusColor } from "./common";

function NavButton({ active, onClick, icon, children }: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} aria-current={active ? "page" : undefined}
            className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] ${
              active ? "bg-signal-soft font-medium text-signal" : "text-ink-soft hover:bg-rule-soft"}`}>
      {icon}
      {children}
    </button>
  );
}

function NewWorkflowForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const queryClient = useQueryClient();
  const openWorkflow = useUi((s) => s.openWorkflow);
  const toast = useUi((s) => s.toast);
  const id = name.toLowerCase().trim().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "")
    .slice(0, 64);
  const create = useMutation({
    mutationFn: () => api.createWorkflow({ id, name: name.trim() }),
    onSuccess: async (workflow) => {
      await queryClient.invalidateQueries({ queryKey: ["workflows"] });
      openWorkflow(workflow.id);
      onDone();
    },
    onError: (error) => toast(error.message),
  });
  return (
    <form className="mt-1 flex flex-col gap-1.5 px-2"
          onSubmit={(e) => { e.preventDefault(); if (id) create.mutate(); }}>
      <input autoFocus className="field" placeholder="Workflow name" value={name}
             onChange={(e) => setName(e.target.value)} aria-label="New workflow name" />
      {name && <span className="meta">id: {id || "—"}</span>}
      <div className="flex gap-1.5">
        <button type="submit" className="btn btn-primary" disabled={!id || create.isPending}>
          {create.isPending ? "Creating…" : "Create"}
        </button>
        <button type="button" className="btn btn-quiet" onClick={onDone}>Cancel</button>
      </div>
    </form>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { view, workflowId, setView, openWorkflow } = useUi();
  const [creating, setCreating] = useState(false);
  const project = useQuery({ queryKey: ["project"], queryFn: api.project });
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: api.workflows,
                               refetchInterval: 5000 });
  const go = (v: View) => () => setView(v);

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-60 shrink-0 flex-col border-r border-rule bg-panel">
        <div className="border-b border-rule px-4 py-3">
          <div className="text-[15px] font-semibold tracking-tight">NeuroWeave</div>
          <div className="meta truncate" title={project.data?.root}>
            {project.isError ? "Server unreachable" : project.data?.name ?? "Loading project…"}
          </div>
        </div>
        <nav className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto p-2" aria-label="Main">
          <div className="flex items-center justify-between px-2 pt-1 pb-1">
            <span className="meta font-medium">Workflows</span>
            <button type="button" className="text-ink-faint hover:text-signal" title="New workflow"
                    aria-label="New workflow" onClick={() => setCreating(true)}>
              <Plus size={15} />
            </button>
          </div>
          {creating && <NewWorkflowForm onDone={() => setCreating(false)} />}
          {workflows.data?.length === 0 && !creating && (
            <p className="px-2 text-[12px] text-ink-faint">No workflows yet.</p>
          )}
          {workflows.data?.map((w) => (
            <NavButton key={w.id} active={view === "workflow" && workflowId === w.id}
                       onClick={() => openWorkflow(w.id)}
                       icon={<span className="h-2 w-2 shrink-0 rounded-full"
                                   style={{ background: statusColor(w.last_run?.status) }}
                                   title={w.last_run ? `Last run ${w.last_run.status.toLowerCase()}`
                                     : "Never run"} />}>
              <span className="truncate">{w.name}</span>
            </NavButton>
          ))}
          <div className="my-2 border-t border-rule-soft" />
          <NavButton active={view === "runs"} onClick={go("runs")} icon={<FlaskConical size={15} />}>
            Runs & experiments
          </NavButton>
          <NavButton active={view === "artifacts"} onClick={go("artifacts")} icon={<Package size={15} />}>
            Artifacts
          </NavButton>
          <NavButton active={view === "nodes"} onClick={go("nodes")} icon={<Boxes size={15} />}>
            Node catalog
          </NavButton>
          <NavButton active={view === "project"} onClick={go("project")} icon={<FolderCog size={15} />}>
            Project settings
          </NavButton>
        </nav>
        <div className="border-t border-rule px-4 py-2 meta flex items-center gap-1.5">
          <WorkflowIcon size={13} /> Local server, v{project.data?.version ?? "…"}
        </div>
      </aside>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</main>
    </div>
  );
}
