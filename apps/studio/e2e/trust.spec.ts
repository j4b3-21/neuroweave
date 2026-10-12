import { expect, openStudio, test } from "./support/fixtures";
import { runFromEditor } from "./support/studio-ui";

const WORKFLOW = "rainfall-yield";

test("opens an untrusted project without importing its code, and runs it once trusted", async ({ page, studio, project, api }) => {
  const saved = project.readWorkflow(WORKFLOW);
  project.setTrusted(false);
  await studio.restart();
  expect(studio.log).toContain("Opening without importing node code");

  await openStudio(page, studio, `workflow/${WORKFLOW}`);
  await expect(page.getByRole("group", { name: "Node load", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeDisabled();
  const catalogProblem = page.getByRole("button", { name: /node catalog could not be loaded/ });
  await catalogProblem.click();
  await expect(page.getByText(/is not trusted, so its node modules were not imported/)).toBeVisible();
  await expect(page.getByText(/trust it with `nw --project .+ trust`/)).toBeVisible();

  const refused = await page.request.post(`${studio.url}/api/workflows/${WORKFLOW}/runs`, {
    data: {}, headers: { "X-NeuroWeave-Client": "e2e" },
  });
  expect(refused.status()).toBe(403);
  expect(await api.runs()).toEqual([]);
  expect(project.readWorkflow(WORKFLOW), "opening must not rewrite the workflow").toEqual(saved);

  project.setTrusted(true);
  await openStudio(page, studio, `workflow/${WORKFLOW}`);
  await expect(catalogProblem).toHaveCount(0);
  const runId = await runFromEditor(page, WORKFLOW);
  expect((await api.waitForRun(runId)).run.status).toBe("SUCCEEDED");
});
