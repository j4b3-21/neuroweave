import { describe, expect, it } from "vitest";

import type { NodeDefinition, TypeSpec, Workflow } from "../api/types";
import {
  addNode, connect, edgeKey, layeredLayout, parseEdgeKey, removeNodes, setParam, typeLabel,
  uniqueNodeId,
} from "./graph";

const def = (name: string): NodeDefinition => ({
  id: `mod:${name}`, name, label: name, module: "mod", qualname: name, version: "1",
  code_hash: null, description: null, category: null, tags: [], inputs: [], outputs: [],
  cache: true,
});

const empty: Workflow = {
  schema_version: 1, id: "wf", name: "wf", description: "", nodes: [], edges: [],
};

describe("graph helpers", () => {
  it("generates unique, valid node ids", () => {
    let wf = addNode(empty, def("load"), 0, 0).workflow;
    wf = addNode(wf, def("load"), 0, 0).workflow;
    expect(wf.nodes.map((n) => n.id)).toEqual(["load", "load_2"]);
    expect(uniqueNodeId(wf, "9 bad name!")).toBe("_9_bad_name_");
  });

  it("connects, clears an overridden param, and refuses a second input", () => {
    let wf = addNode(empty, def("a"), 0, 0).workflow;
    wf = addNode(wf, def("b"), 0, 0).workflow;
    wf = setParam(wf, "b", "x", 3);
    const edge = { source: "a", source_port: "output", target: "b", target_port: "x" };
    const result = connect(wf, edge);
    if ("error" in result) throw new Error(result.error);
    expect(result.workflow.nodes[1]!.params).toEqual({});
    expect(connect(result.workflow, edge)).toEqual({
      error: "Input 'x' of 'b' is already connected.",
    });
    expect("error" in connect(wf, { ...edge, target: "a" })).toBe(true);
    expect(removeNodes(result.workflow, new Set(["a"])).edges).toEqual([]);
  });

  it("round-trips edge keys", () => {
    const edge = { source: "load_2", source_port: "output", target: "stats", target_port: "data" };
    expect(parseEdgeKey(edgeKey(edge))).toEqual(edge);
  });

  it("formats types", () => {
    const int: TypeSpec = { kind: "primitive", name: "int", args: [], values: [], bases: [] };
    expect(typeLabel({ kind: "list", name: "list", args: [int], values: [], bases: [] }))
      .toBe("list[int]");
    expect(typeLabel({ kind: "optional", name: "Optional", args: [int], values: [], bases: [] }))
      .toBe("int | None");
  });

  it("lays out by dependency depth", () => {
    const layout = layeredLayout(["a", "b", "c"], [{ source: "a", target: "b" },
      { source: "b", target: "c" }, { source: "a", target: "c" }]);
    expect(layout.get("c")!.x).toBeGreaterThan(layout.get("b")!.x);
  });
});
