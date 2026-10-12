import { expect, openStudio, test } from "./support/fixtures";

const WORKFLOW = "rainfall-yield";
const edgeKey = (e: { source: string; source_port: string; target: string; target_port: string }) =>
  `${e.source}.${e.source_port}->${e.target}.${e.target_port}`;

test("opens a saved workflow and renders every node and connection", async ({ page, studio, project }) => {
  const saved = project.readWorkflow(WORKFLOW);
  await openStudio(page, studio, `workflow/${WORKFLOW}`);

  await expect(page.getByRole("heading", { level: 1, name: saved.name })).toBeVisible();
  const canvas = page.locator(".react-flow");
  await expect(canvas.locator("[aria-roledescription=node]")).toHaveCount(saved.nodes.length);
  for (const node of saved.nodes) {
    await expect(canvas.getByRole("group", { name: `Node ${node.id}`, exact: true })).toBeVisible();
  }
  await expect(canvas.locator("[aria-roledescription=edge]")).toHaveCount(saved.edges.length);
  for (const edge of saved.edges) {
    await expect(canvas.getByRole("group", { name: `Connection ${edgeKey(edge)}`, exact: true }))
      .toBeAttached();
  }

  const inspector = page.getByRole("complementary", { name: "Inspector" });
  await expect(inspector.getByText("valid", { exact: true })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: /^Saved$/ })).toBeVisible();
});

test("edits a node parameter and persists it through the API to disk", async ({ page, studio, project, api }) => {
  const before = await api.workflow(WORKFLOW);
  expect(before.workflow.nodes.find((n) => n.id === "bootstrap")?.params).toEqual({ resamples: 500 });
  await openStudio(page, studio, `workflow/${WORKFLOW}`);

  await page.getByRole("group", { name: "Node bootstrap", exact: true }).click();
  const inspector = page.getByRole("complementary", { name: "Inspector" });
  const resamples = inspector.getByRole("textbox", { name: "Parameter resamples" });
  await expect(resamples).toHaveValue("500");

  const saved = page.waitForResponse((r) => r.request().method() === "PUT"
    && r.url().endsWith(`/api/workflows/${WORKFLOW}`));
  await resamples.fill("300");
  await resamples.press("Enter");
  const response = await saved;
  expect(response.status()).toBe(200);
  await expect(page.getByRole("status").filter({ hasText: /^Saved$/ })).toBeVisible();

  // Persisted state, read independently of the browser: the API and the file on disk.
  const after = await api.workflow(WORKFLOW);
  expect(after.workflow.nodes.find((n) => n.id === "bootstrap")?.params).toEqual({ resamples: 300 });
  expect(after.revision).not.toBe(before.revision);
  expect((await response.json()).revision).toBe(after.revision);
  const onDisk = project.readWorkflow(WORKFLOW);
  expect(onDisk.nodes.find((n) => n.id === "bootstrap")?.params).toEqual({ resamples: 300 });
  // Nothing else changed.
  const others = (w: typeof onDisk) => w.nodes.filter((n) => n.id !== "bootstrap").map((n) => n.params);
  expect(others(onDisk)).toEqual(others(before.workflow as typeof onDisk));
  expect(onDisk.edges).toHaveLength(9);

  await page.reload();
  await page.getByRole("group", { name: "Node bootstrap", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Inspector" })
    .getByRole("textbox", { name: "Parameter resamples" })).toHaveValue("300");
});

test("rejects an invalid workflow with an actionable validation error", async ({ page, studio, project, api }) => {
  await openStudio(page, studio, `workflow/${WORKFLOW}`);
  const canvas = page.locator(".react-flow");

  // 1. A type-incompatible connection (Table output into a str input) is refused, not saved.
  const source = canvas.getByRole("group", { name: "Node transform", exact: true })
    .getByLabel("Output port output");
  const target = canvas.getByRole("group", { name: "Node plot", exact: true })
    .getByLabel("Input port x");
  const from = (await source.boundingBox())!;
  const to = (await target.boundingBox())!;
  const checked = page.waitForResponse((r) => r.url().endsWith(`/api/workflows/${WORKFLOW}/validate`)
    && r.request().method() === "POST");
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 12 });
  await page.mouse.up();
  await checked;
  await expect(page.getByRole("alert").filter({ hasText: "Cannot connect transform.output" }))
    .toContainText("to plot.x (str)");
  await expect(canvas.locator("[aria-roledescription=edge]")).toHaveCount(9);
  expect(project.readWorkflow(WORKFLOW).edges).toHaveLength(9);

  // 2. Clearing a required parameter makes the saved workflow invalid; the Studio says what is
  //    wrong and where, and refuses to run it.
  await canvas.getByRole("group", { name: "Node load", exact: true }).click();
  const inspector = page.getByRole("complementary", { name: "Inspector" });
  await expect(inspector.getByRole("textbox", { name: "Parameter path" })).toHaveValue("data/field_trial.csv");
  await inspector.getByRole("button", { name: "reset" }).click();
  await expect(page.getByRole("status").filter({ hasText: /^Saved$/ })).toBeVisible();
  expect(project.readWorkflow(WORKFLOW).nodes.find((n) => n.id === "load")?.params).toEqual({});

  const run = page.getByRole("button", { name: "Run", exact: true });
  await expect(run).toBeDisabled();
  await expect(run).toHaveAttribute("title", "Fix the problems listed below before running.");
  await page.getByRole("tab", { name: /^Problems/ }).click();
  const problem = page.getByRole("row").filter({ hasText: "missing_input" });
  await expect(problem).toContainText("load");
  await expect(problem).toContainText("path");

  // The server enforces the same rule independently of the UI: nothing is executed.
  const refused = await page.request.post(`${studio.url}/api/workflows/${WORKFLOW}/runs`, {
    data: {}, headers: { "X-NeuroWeave-Client": "e2e" },
  });
  expect(refused.status()).toBe(422);
  const body = await refused.json();
  expect(body.detail.message).toBe("Workflow is invalid; nothing was executed.");
  expect(body.detail.validation.issues.map((i: { code: string }) => i.code)).toContain("missing_input");
  expect(await api.runs(WORKFLOW)).toEqual([]);
});
