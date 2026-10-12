import type { Page } from "@playwright/test";

import { byNode } from "./support/api";
import { expect, openStudio, test } from "./support/fixtures";

/** Click Reproduce on the open run and return the id of the reproduction run. */
async function reproduceFromRunDetail(page: Page, runId: string): Promise<string> {
  const started = page.waitForResponse((r) => r.request().method() === "POST"
    && r.url().endsWith(`/api/runs/${runId}/reproduce`));
  await page.getByRole("button", { name: "Reproduce" }).click();
  const response = await started;
  expect(response.status()).toBe(202);
  return (await response.json()).id as string;
}

test("reproduces a deterministic run under the exact-content-hash policy", async ({ page, studio, api }) => {
  const original = await api.waitForRun((await api.startRun("rainfall-yield")).id);
  expect(original.run.status).toBe("SUCCEEDED");
  await openStudio(page, studio, `runs/${original.run.id}`);

  const reproductionId = await reproduceFromRunDetail(page, original.run.id);
  await expect(page).toHaveURL(new RegExp(`#/runs/${reproductionId}$`));
  const reproduction = await api.waitForRun(reproductionId);

  // What the check actually did: a new run of the same snapshot and seed with caching off, in
  // which every node really executed.
  expect(reproduction.run).toMatchObject({
    status: "SUCCEEDED", trigger: "reproduce", use_cache: false, reproduces_run_id: original.run.id,
    snapshot_hash: original.run.snapshot_hash, seed: original.run.seed,
  });
  for (const { execution } of reproduction.nodes) {
    expect(execution.cache_hit, execution.node_id).toBe(false);
    expect(execution.cache_note, execution.node_id).toBe("caching disabled for this run");
  }

  // The verdict compares SHA-256 hashes of every original output with the re-execution's.
  const report = await api.reproduction(reproductionId);
  expect(report.verdict).toBe("reproduced");
  expect(report.policy).toMatch(/^exact-content-hash:/);
  const originalOutputs = byNode(original);
  const reproducedOutputs = byNode(reproduction);
  expect(report.outputs).toHaveLength(original.nodes.length);
  for (const check of report.outputs) {
    expect(check.identical).toBe(true);
    expect(check.original).toBe(originalOutputs.get(check.node_id)!.outputs[0]!.content_hash);
    expect(check.reproduced).toBe(reproducedOutputs.get(check.node_id)!.outputs[0]!.content_hash);
    expect(check.reproduced).toBe(check.original);
  }

  const verdict = page.locator("section").filter({ has: page.getByRole("heading", { name: "Reproduction verdict" }) });
  await expect(verdict).toContainText("Reproduced: the re-execution produced byte-identical outputs (equal SHA-256)");
  await expect(verdict).toContainText(report.policy);
  await expect(verdict).toContainText(`${original.nodes.length} (0 differ)`);
  await expect(verdict).toContainText("The original environment is not recreated");
  await expect(verdict.getByRole("button", { name: original.run.id })).toBeVisible();

  // The original run lists its reproduction.
  await verdict.getByRole("button", { name: original.run.id }).click();
  const list = page.locator("section").filter({ has: page.getByRole("heading", { name: "Reproductions of this run" }) });
  await expect(list.getByRole("button", { name: reproductionId })).toBeVisible();
});

test("reports a nondeterministic run as not reproduced and shows the differing hashes", async ({ page, studio, api }) => {
  const original = await api.waitForRun((await api.startRun("nondeterministic")).id);
  expect(original.run.status).toBe("SUCCEEDED");
  await openStudio(page, studio, `runs/${original.run.id}`);

  const reproductionId = await reproduceFromRunDetail(page, original.run.id);
  expect((await api.waitForRun(reproductionId)).run.status).toBe("SUCCEEDED");
  const report = await api.reproduction(reproductionId);
  expect(report.verdict).toBe("not_reproduced");
  expect(report.outputs).toHaveLength(1);
  const [check] = report.outputs;
  expect(check).toMatchObject({ node_id: "token", port: "output", identical: false });
  expect(check!.original).toBe(original.nodes[0]!.outputs[0]!.content_hash);
  expect(check!.reproduced).not.toBe(check!.original);

  const verdict = page.locator("section").filter({ has: page.getByRole("heading", { name: "Reproduction verdict" }) });
  await expect(verdict).toContainText("Not reproduced: at least one output of the re-execution is missing or differs.");
  await expect(verdict).toContainText("1 (1 differ)");
  const row = verdict.getByRole("row").filter({ hasText: "token.output" });
  await expect(row.getByRole("button", { name: check!.original!.slice(0, 10) })).toBeVisible();
  await expect(row.getByRole("button", { name: check!.reproduced!.slice(0, 10) })).toBeVisible();
});
