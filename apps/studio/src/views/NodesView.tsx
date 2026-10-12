import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import { EmptyState, ErrorText, Hash, KeyValue, Section } from "../components/common";
import { formatTime } from "../lib/format";
import { typeLabel } from "../lib/graph";

export function NodesView() {
  const queryClient = useQueryClient();
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.catalog() });
  const [refreshing, setRefreshing] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const definitions = catalog.data?.definitions ?? [];
  const selected = definitions.find((d) => d.id === selectedId) ?? definitions[0];

  const refresh = async () => {
    setRefreshing(true);
    try {
      queryClient.setQueryData(["catalog"], await api.catalog(true));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-80 shrink-0 flex-col border-r border-rule">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-rule bg-panel px-4">
          <h1 className="text-[15px] font-semibold">Node catalog</h1>
          <button type="button" className="btn ml-auto" onClick={() => void refresh()} disabled={refreshing}
                  title="Re-import node modules in a fresh process">
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} /> Reload
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto bg-panel">
          {catalog.error && <div className="p-4"><ErrorText error={catalog.error} /></div>}
          {catalog.data && catalog.data.errors.length > 0 && (
            <div className="border-b border-rule bg-fail/5 px-4 py-2">
              {catalog.data.errors.map((e) => (
                <details key={e.module} className="text-[12px] text-fail">
                  <summary className="cursor-pointer">Module '{e.module}' failed: {e.error}</summary>
                  <pre className="mt-1 overflow-x-auto font-mono text-[11px] whitespace-pre-wrap">{e.traceback}</pre>
                </details>
              ))}
            </div>
          )}
          <ul>
            {definitions.map((d) => (
              <li key={d.id}>
                <button type="button" onClick={() => setSelectedId(d.id)}
                        className={`block w-full border-b border-rule-soft px-4 py-2 text-left ${
                          d.id === selected?.id ? "bg-signal-soft" : "hover:bg-rule-soft"}`}>
                  <div className="text-[13px] font-medium">{d.label}</div>
                  <div className="truncate font-mono text-[11px] text-ink-faint">{d.id}</div>
                </button>
              </li>
            ))}
          </ul>
          {catalog.data && (
            <p className="meta px-4 py-2">Loaded {formatTime(catalog.data.loaded_at)}. Nodes are
              discovered by importing the project's node modules in a separate process.</p>
          )}
        </div>
      </div>
      <div className="min-w-0 flex-1 overflow-y-auto bg-panel">
        {!selected ? (
          <EmptyState title="No nodes registered">
            Write Python functions decorated with <code>@node</code> and list their module under Project
            settings.
          </EmptyState>
        ) : (
          <>
            <header className="border-b border-rule px-4 py-3">
              <h2 className="text-[15px] font-semibold">{selected.label}</h2>
              {selected.description && <p className="mt-1 max-w-2xl text-[13px] text-ink-soft">{selected.description}</p>}
            </header>
            <Section title="Definition">
              <KeyValue rows={[
                ["Id", <span className="hash">{selected.id}</span>],
                ["Version", selected.version],
                ["Code hash", <Hash value={selected.code_hash} length={16} />],
                ["Category", selected.category ?? "—"],
                ["Tags", selected.tags.length ? selected.tags.join(", ") : "—"],
                ["Caching", selected.cache ? "results may be reused" : "always re-executed"],
              ]} />
            </Section>
            <Section title="Inputs">
              {selected.inputs.length === 0 ? <p className="meta">None.</p> : (
                <table className="data-table">
                  <thead><tr><th>Name</th><th>Type</th><th>Default</th><th>Set as</th></tr></thead>
                  <tbody>
                    {selected.inputs.map((p) => (
                      <tr key={p.name}>
                        <td>{p.name}{p.required && <span className="text-fail"> *</span>}</td>
                        <td className="font-mono text-[12px]">{typeLabel(p.type)}</td>
                        <td className="font-mono text-[12px]">{p.has_default ? p.default_repr : "—"}</td>
                        <td className="text-[12px] text-ink-soft">
                          {p.editable ? `parameter (${p.widget}) or connection` : "connection only"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>
            <Section title="Outputs">
              <table className="data-table">
                <thead><tr><th>Name</th><th>Type</th></tr></thead>
                <tbody>
                  {selected.outputs.map((p) => (
                    <tr key={p.name}>
                      <td>{p.name}</td>
                      <td className="font-mono text-[12px]">{typeLabel(p.type)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          </>
        )}
      </div>
    </div>
  );
}
