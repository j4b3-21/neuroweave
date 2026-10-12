import { byNode } from "./support/api";
import { expect, openStudio, test } from "./support/fixtures";
import { latestRunRow, runFromEditor } from "./support/studio-ui";

const WORKFLOW = "failure-demo";
const MESSAGE = "RuntimeError: Deliberate failure for the browser test";
const SKIPPED = "Skipped because upstream node(s) explode did not succeed.";

test("records a failing node, skips downstream nodes and exposes the traceback", async ({ page, studio, api }) => {
  await openStudio(page, studio, `workflow/${WORKFLOW}`);
  const runId = await runFromEditor(page, WORKFLOW);
  const detail = await api.waitForRun(runId);

  // Recorded state.
  expect(detail.run.status).toBe("FAILED");
  expect(detail.run.error).toBe("Node(s) failed: explode.");
  const nodes = byNode(detail);
  expect(nodes.get("numbers")!.execution.status).toBe("SUCCEEDED");
  const explode = nodes.get("explode")!;
  expect(explode.execution).toMatchObject({ status: "FAILED", error_type: "RuntimeError", error: MESSAGE });
  expect(explode.execution.traceback).toContain("raise RuntimeError(message)");
  expect(explode.outputs).toEqual([]);
  const total = nodes.get("total")!;
  expect(total.execution).toMatchObject({ status: "SKIPPED", error: SKIPPED, error_type: null });
  expect(total.outputs).toEqual([]);
  expect(await api.logs(runId, "explode")).toContain("explode received 4 values");

  // The editor shows the failure, with each node's own message.
  const strip = page.locator("span").getByText("Latest run", { exact: true }).locator("..");
  await expect(strip).toContainText("Failed");
  await expect(latestRunRow(page, "numbers")).toContainText("Succeeded");
  await expect(latestRunRow(page, "explode")).toContainText("Failed");
  await expect(latestRunRow(page, "explode").getByRole("cell").last()).toHaveText(MESSAGE);
  await expect(latestRunRow(page, "total")).toContainText("Skipped");
  await expect(latestRunRow(page, "total").getByRole("cell").last()).toHaveText(SKIPPED);

  // Inspecting the failed node shows its error, and its log with the traceback.
  await page.getByRole("group", { name: "Node explode", exact: true }).click();
  const inspector = page.getByRole("complementary", { name: "Inspector" });
  await expect(inspector.getByText(MESSAGE, { exact: true })).toBeVisible();
  await inspector.getByRole("button", { name: "Logs" }).click();
  await expect(page.getByRole("tab", { name: "Logs" })).toHaveAttribute("aria-selected", "true");
  const traceback = page.locator("pre").filter({ hasText: "Traceback (most recent call last)" }).first();
  await expect(traceback).toContainText(MESSAGE);
  await expect(page.getByText("explode received 4 values")).toBeVisible();

  // The run history keeps the failure, and the run page offers the traceback.
  await page.getByRole("navigation", { name: "Main" }).getByRole("button", { name: "Runs & experiments" }).click();
  await page.getByRole("checkbox", { name: `Select run ${runId} for comparison` }).locator("xpath=ancestor::tr").click();
  const main = page.getByRole("main");
  await expect(main.getByText("Node(s) failed: explode.")).toBeVisible();
  const summary = main.locator("summary").filter({ hasText: MESSAGE });
  await expect(summary).toHaveText(MESSAGE);
  await summary.click();
  await expect(main.locator("details[open] pre")).toContainText("raise RuntimeError(message)");
  const totalRow = main.getByRole("row").filter({ has: page.getByRole("button", { name: "total", exact: true }) });
  await expect(totalRow).toContainText("Skipped");
  await expect(totalRow).not.toContainText("Succeeded");
});
