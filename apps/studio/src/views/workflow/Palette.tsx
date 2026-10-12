import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import type { Catalog, NodeDefinition } from "../../api/types";
import { typeLabel } from "../../lib/graph";
import { useUi } from "../../state/ui";

export const DRAG_MIME = "application/x-neuroweave-node";

function signature(definition: NodeDefinition): string {
  const inputs = definition.inputs.map((p) => `${p.name}: ${typeLabel(p.type)}`).join(", ");
  const outputs = definition.outputs.map((p) => typeLabel(p.type)).join(", ");
  return `${definition.name}(${inputs}) -> ${outputs}`;
}

export function Palette({ catalog, onAdd }: {
  catalog: Catalog | undefined;
  onAdd: (definition: NodeDefinition) => void;
}) {
  const [filter, setFilter] = useState("");
  const setView = useUi((s) => s.setView);
  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const map = new Map<string, NodeDefinition[]>();
    for (const definition of catalog?.definitions ?? []) {
      const haystack = `${definition.label} ${definition.id} ${definition.tags.join(" ")}`.toLowerCase();
      if (needle && !haystack.includes(needle)) continue;
      const group = definition.category ?? definition.module;
      map.set(group, [...(map.get(group) ?? []), definition]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [catalog, filter]);

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-rule bg-panel"
           aria-label="Node palette" data-tour="palette">
      <div className="border-b border-rule p-2">
        <div className="relative">
          <Search size={14} className="absolute top-1/2 left-2 -translate-y-1/2 text-ink-faint" />
          <input className="field pl-7" placeholder="Find a node" value={filter}
                 onChange={(e) => setFilter(e.target.value)} aria-label="Filter nodes" />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {catalog && catalog.errors.length > 0 && (
          <button type="button" onClick={() => setView("nodes")}
                  className="mb-2 w-full rounded-md bg-fail/5 px-2 py-1.5 text-left text-[12px] text-fail">
            {catalog.errors.some((e) => e.module === "*")
              ? "The node catalog could not be loaded."
              : `${catalog.errors.length} node module(s) failed to load.`} Details
          </button>
        )}
        {!catalog && <p className="meta px-1">Loading node catalog…</p>}
        {catalog && catalog.definitions.length === 0 && (
          <p className="meta px-1">
            No nodes found. Add a module with <code>@node</code> functions under Project settings.
          </p>
        )}
        {groups.map(([group, definitions]) => (
          <div key={group} className="mb-3">
            <div className="meta mb-1 px-1 font-medium">{group}</div>
            {definitions.map((definition) => (
              <button key={definition.id} type="button" draggable title={signature(definition)}
                      onClick={() => onAdd(definition)}
                      onDragStart={(e) => {
                        e.dataTransfer.setData(DRAG_MIME, definition.id);
                        e.dataTransfer.effectAllowed = "copy";
                      }}
                      className="block w-full cursor-grab rounded-md px-2 py-1 text-left text-[13px] hover:bg-rule-soft active:cursor-grabbing">
                <span className="block truncate">{definition.label}</span>
                <span className="block truncate text-[11px] text-ink-faint">
                  {definition.inputs.length} in, {definition.outputs.length} out
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>
      <p className="meta border-t border-rule px-3 py-2">Click to add, or drag onto the canvas.</p>
    </aside>
  );
}
