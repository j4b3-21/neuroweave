import { expect, type Page } from "@playwright/test";

/** Click Run in the workflow editor and return the id of the run the server created. */
export async function runFromEditor(page: Page, workflowId: string): Promise<string> {
  const started = page.waitForResponse((r) => r.request().method() === "POST"
    && r.url().endsWith(`/api/workflows/${workflowId}/runs`));
  const run = page.getByRole("button", { name: "Run", exact: true });
  await expect(run).toBeEnabled();
  await run.click();
  const response = await started;
  expect(response.status(), await response.text()).toBe(202);
  return (await response.json()).id as string;
}

/** Set a parameter of a node through the inspector and wait until the Studio reports it saved. */
export async function setParameter(page: Page, nodeId: string, param: string, value: string): Promise<void> {
  await page.getByRole("group", { name: `Node ${nodeId}`, exact: true }).click();
  const field = page.getByRole("complementary", { name: "Inspector" })
    .getByRole("textbox", { name: `Parameter ${param}` });
  const saved = page.waitForResponse((r) => r.request().method() === "PUT" && r.ok());
  await field.fill(value);
  await field.press("Enter");
  await saved;
  await expect(page.getByRole("status").filter({ hasText: /^Saved$/ })).toBeVisible();
}

/** The row for one node in the editor's "Latest run" panel. */
export function latestRunRow(page: Page, nodeId: string) {
  return page.getByRole("row").filter({ has: page.getByRole("cell", { name: nodeId, exact: true }) });
}

/** Workflow nodes downstream of (and including) `start`, from the saved edge list. */
export function downstreamOf(edges: { source: string; target: string }[], start: string): Set<string> {
  const result = new Set([start]);
  for (let grew = true; grew;) {
    grew = false;
    for (const edge of edges) {
      if (result.has(edge.source) && !result.has(edge.target)) {
        result.add(edge.target);
        grew = true;
      }
    }
  }
  return result;
}
