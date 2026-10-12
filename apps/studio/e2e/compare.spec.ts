import { formatNumber } from "../src/lib/format";
import { expect, openStudio, test } from "./support/fixtures";
import { runFromEditor, setParameter } from "./support/studio-ui";

const WORKFLOW = "rainfall-yield";

test("compares two runs with different parameters", async ({ page, studio, api }) => {
  await openStudio(page, studio, `workflow/${WORKFLOW}`);
  const runA = await runFromEditor(page, WORKFLOW);
  expect((await api.waitForRun(runA)).run.status).toBe("SUCCEEDED");
  await setParameter(page, "bootstrap", "resamples", "300");
  const runB = await runFromEditor(page, WORKFLOW);
  expect((await api.waitForRun(runB)).run.status).toBe("SUCCEEDED");

  await page.getByRole("navigation", { name: "Main" }).getByRole("button", { name: "Runs & experiments" }).click();
  await page.getByRole("checkbox", { name: `Select run ${runA} for comparison` }).check();
  await page.getByRole("checkbox", { name: `Select run ${runB} for comparison` }).check();
  const compared = page.waitForResponse((r) => r.url().includes("/api/compare?"));
  await page.getByRole("button", { name: "Compare (2/2)" }).click();
  const request = new URL((await compared).url());
  expect([request.searchParams.get("a"), request.searchParams.get("b")]).toEqual([runA, runB]);

  // The comparison is computed by the server; check the UI against it and against the runs.
  const c = await api.compare(runA, runB);
  expect([c.run_a.id, c.run_b.id]).toEqual([runA, runB]);
  expect(c.same_snapshot).toBe(false);
  const bootstrap = c.nodes.find((n) => n.node_id === "bootstrap")!;
  expect(bootstrap.param_changes).toEqual({ resamples: [500, 300] });
  const differing = c.nodes.filter((n) => Object.values(n.outputs).some((o) => !o.identical))
    .map((n) => n.node_id);
  expect(differing).toEqual(["bootstrap", "report"]);
  const width = c.metrics.find((m) => m.node_id === "bootstrap" && m.name === "slope_ci_width")!;
  expect(width.a).not.toBe(width.b);
  const runs = await Promise.all([api.run(runA), api.run(runB)]);
  for (const [index, detail] of runs.entries()) {
    const logged = detail.metrics.filter((m) => m.node_id === "bootstrap" && m.name === "slope_ci_width");
    expect(logged.map((m) => m.value)).toEqual([index === 0 ? width.a : width.b]);
  }

  const view = page.getByRole("main");
  await expect(view.getByText(runA, { exact: true })).toBeVisible();
  await expect(view.getByText(runB, { exact: true })).toBeVisible();
  await expect(view.getByRole("listitem").filter({ hasText: "Parameters changed in: bootstrap." })).toBeVisible();
  await expect(view.getByRole("listitem").filter({ hasText: "Outputs differ for: bootstrap, report." })).toBeVisible();
  await expect(view.getByRole("listitem").filter({ hasText: "~ bootstrap: resamples 500 to 300" })).toBeVisible();

  const metricRow = view.getByRole("row").filter({ hasText: "slope_ci_width" });
  await expect(metricRow.getByRole("cell")).toHaveText([
    "bootstrap", "slope_ci_width (minimize)", formatNumber(width.a), formatNumber(width.b),
    `${width.delta! > 0 ? "+" : ""}${formatNumber(width.delta)}`,
  ]);

  const nodes = view.locator("section").filter({ has: page.getByRole("heading", { name: "Nodes", exact: true }) });
  const nodeRow = (id: string) => nodes.getByRole("row")
    .filter({ has: page.getByRole("cell", { name: id, exact: true }) });
  await expect(nodeRow("bootstrap")).toContainText("resamples: 500 to 300");
  for (const id of differing) {
    await expect(nodeRow(id)).toContainText("differs");
  }
  for (const id of ["load", "validate", "transform", "statistics", "plot"]) {
    await expect(nodeRow(id)).toContainText("identical");
    await expect(nodeRow(id).getByRole("cell").nth(2)).toHaveText("Reused");
  }
});
