import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { ErrorText, KeyValue, Section } from "../components/common";
import { useUi } from "../state/ui";

export function ProjectView() {
  const queryClient = useQueryClient();
  const toast = useUi((s) => s.toast);
  const project = useQuery({ queryKey: ["project"], queryFn: api.project });
  const [name, setName] = useState("");
  const [modules, setModules] = useState("");
  const [seed, setSeed] = useState("");

  useEffect(() => {
    if (!project.data) return;
    setName(project.data.name);
    setModules(project.data.node_modules.join("\n"));
    setSeed(String(project.data.default_seed));
  }, [project.data]);

  const save = useMutation({
    mutationFn: () => {
      const parsedSeed = Number(seed);
      if (!Number.isInteger(parsedSeed) || parsedSeed < 0) throw new Error("Default seed must be a non-negative integer.");
      return api.updateProject({
        name: name.trim(),
        node_modules: modules.split("\n").map((m) => m.trim()).filter(Boolean),
        default_seed: parsedSeed,
      });
    },
    onSuccess: async (info) => {
      queryClient.setQueryData(["project"], info);
      queryClient.setQueryData(["catalog"], await api.catalog(true));
      toast("Project settings saved and node modules reloaded.", "info");
    },
    onError: (error) => toast(error.message),
  });

  if (project.error) return <div className="p-6"><ErrorText error={project.error} /></div>;
  if (!project.data) return <p className="meta p-6">Loading…</p>;

  return (
    <div className="h-full overflow-y-auto">
      <header className="flex h-12 items-center border-b border-rule bg-panel px-4">
        <h1 className="text-[15px] font-semibold">Project settings</h1>
      </header>
      <div className="max-w-2xl bg-panel">
        <Section title="Location">
          <KeyValue rows={[
            ["Root", <span className="hash break-all">{project.data.root}</span>],
            ["Workflows", project.data.workflow_count],
            ["Runs", project.data.run_count],
            ["NeuroWeave", project.data.version],
          ]} />
        </Section>
        <Section title="Settings">
          <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <label className="flex flex-col gap-1 text-[13px]">
              <span className="font-medium">Project name</span>
              <input className="field" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1 text-[13px]">
              <span className="font-medium">Node modules</span>
              <textarea className="field font-mono text-[12px]" rows={4} value={modules}
                        onChange={(e) => setModules(e.target.value)} />
              <span className="meta">One importable Python module or package per line, resolved from the
                project root (for example <code>demo_nodes</code> or <code>lab.nodes</code>). Importing a
                module runs its code with your user permissions; only list code you trust.</span>
            </label>
            <label className="flex flex-col gap-1 text-[13px]">
              <span className="font-medium">Default seed</span>
              <input className="field w-40" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} />
              <span className="meta">Used when a run does not specify a seed. Each node receives a seed derived
                from this value and its id.</span>
            </label>
            <div>
              <button type="submit" className="btn btn-primary" disabled={save.isPending}>
                {save.isPending ? "Saving…" : "Save settings"}
              </button>
            </div>
          </form>
        </Section>
      </div>
    </div>
  );
}
