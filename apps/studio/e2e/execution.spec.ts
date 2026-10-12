import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

import { byNode } from "./support/api";
import { expect, openStudio, test } from "./support/fixtures";
import { downstreamOf, latestRunRow, runFromEditor, setParameter } from "./support/studio-ui";

const WORKFLOW = "rainfall-yield";

test("runs a deterministic workflow and records outputs and the executed snapshot", async ({ page, studio, project, api }) => {
  const saved = project.readWorkflow(WORKFLOW);
  const { revision } = await api.workflow(WORKFLOW);
  await openStudio(page, studio, `workflow/${WORKFLOW}`);

  const runId = await runFromEditor(page, WORKFLOW);
  const detail = await api.waitForRun(runId);

  // Run record.
  expect(detail.run.status, detail.run.error ?? "").toBe("SUCCEEDED");
  expect(detail.run).toMatchObject({ workflow_id: WORKFLOW, trigger: "studio", use_cache: true, seed: 0 });
  expect(detail.run.snapshot_hash).toBe(revision);
  expect(project.snapshotExists(detail.run.snapshot_hash)).toBe(true);
  expect(detail.workflow).toEqual(JSON.parse(readFileSync(
    path.join(project.workspaceDir, "snapshots", `${detail.run.snapshot_hash}.json`), "utf-8")));
  expect(detail.workflow.nodes.map((n) => [n.id, n.params]))
    .toEqual(saved.nodes.map((n) => [n.id, n.params]));

  // Every node executed (fresh project, nothing to reuse) and produced one stored output.
  expect(detail.nodes.map((n) => n.execution.node_id).sort()).toEqual(saved.nodes.map((n) => n.id).sort());
  for (const { execution, outputs } of detail.nodes) {
    expect(execution.status).toBe("SUCCEEDED");
    expect(execution.cache_hit).toBe(false);
    expect(outputs).toHaveLength(1);
  }
  const outputs = await api.artifacts(runId, "output");
  expect(outputs).toHaveLength(saved.nodes.length);
  for (const artifact of outputs) {
    expect(artifact.stored).toBe(true);
    expect(project.hashStoredObject(artifact.content_hash)).toBe(artifact.content_hash);
    expect(readFileSync(project.objectPath(artifact.content_hash)).length).toBe(artifact.size);
  }
  // The CSV the load node read is recorded as an input with the hash of the file on disk.
  const [input] = await api.artifacts(runId, "input");
  const csv = readFileSync(path.join(project.root, "data", "field_trial.csv"));
  expect(input?.content_hash).toBe(createHash("sha256").update(csv).digest("hex"));

  // The Studio shows the finished run.
  await expect(page.getByRole("tab", { name: "Latest run" })).toHaveAttribute("aria-selected", "true");
  for (const node of saved.nodes) {
    await expect(latestRunRow(page, node.id)).toContainText("Succeeded");
  }
  await expect(page.getByText(runId, { exact: true })).toBeVisible();
});

test("reruns only nodes affected by a parameter change and reuses the rest", async ({ page, studio, project, api }) => {
  await openStudio(page, studio, `workflow/${WORKFLOW}`);
  const firstId = await runFromEditor(page, WORKFLOW);
  const first = await api.waitForRun(firstId);
  expect(first.run.status).toBe("SUCCEEDED");

  await setParameter(page, "bootstrap", "resamples", "300");
  const secondId = await runFromEditor(page, WORKFLOW);
  const second = await api.waitForRun(secondId);
  expect(second.run.status, second.run.error ?? "").toBe("SUCCEEDED");

  // Expected re-executions follow from the graph: the edited node and everything downstream.
  const affected = downstreamOf(project.readWorkflow(WORKFLOW).edges, "bootstrap");
  expect([...affected].sort()).toEqual(["bootstrap", "report"]);

  const a = byNode(first);
  const b = byNode(second);
  expect([...b.keys()].sort()).toEqual([...a.keys()].sort());
  for (const [nodeId, { execution, outputs }] of b) {
    const previous = a.get(nodeId)!;
    if (affected.has(nodeId)) {
      expect(execution.cache_hit, nodeId).toBe(false);
      expect(execution.cache_source_id, nodeId).toBeNull();
      expect(outputs[0]!.reused_from, nodeId).toBeNull();
      expect(outputs[0]!.content_hash, nodeId).not.toBe(previous.outputs[0]!.content_hash);
    } else {
      expect(execution.cache_hit, nodeId).toBe(true);
      expect(execution.cache_source_id, nodeId).toBe(previous.execution.id);
      expect(execution.cache_key, nodeId).toBe(previous.execution.cache_key);
      expect(outputs[0]!.reused_from, nodeId).toBe(previous.outputs[0]!.id);
      expect(outputs[0]!.content_hash, nodeId).toBe(previous.outputs[0]!.content_hash);
    }
  }

  // The new run records the changed parameter and snapshot; the earlier run is untouched.
  expect(b.get("bootstrap")!.execution.params.resamples).toBe(300);
  expect(a.get("bootstrap")!.execution.params.resamples).toBe(500);
  expect(second.run.snapshot_hash).not.toBe(first.run.snapshot_hash);
  expect(second.workflow.nodes.find((n) => n.id === "bootstrap")?.params).toEqual({ resamples: 300 });
  expect(await api.run(firstId)).toEqual(first);

  // Lineage of the new report: fresh bootstrap output, and reused nodes linked to the
  // executions whose results they reused.
  const report = b.get("report")!;
  const lineage = await api.lineage(report.outputs[0]!.id);
  const ids = new Set(lineage.nodes.map((n) => n.id));
  expect(ids.has(b.get("bootstrap")!.outputs[0]!.id)).toBe(true);
  expect(ids.has(a.get("bootstrap")!.outputs[0]!.id)).toBe(false);
  expect(lineage.edges).toContainEqual({ source: b.get("bootstrap")!.outputs[0]!.id,
    target: report.execution.id, relation: "used", basis: "observed" });
  expect(lineage.edges).toContainEqual({ source: a.get("statistics")!.execution.id,
    target: b.get("statistics")!.execution.id, relation: "reusedResultOf", basis: "observed" });

  // The Studio shows which nodes were reused.
  for (const nodeId of b.keys()) {
    await expect(latestRunRow(page, nodeId)).toContainText(affected.has(nodeId) ? "Succeeded" : "Reused");
  }
});
