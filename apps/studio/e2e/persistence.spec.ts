import { byNode } from "./support/api";
import { expect, openStudio, test } from "./support/fixtures";
import { runFromEditor, setParameter } from "./support/studio-ui";

const WORKFLOW = "rainfall-yield";

test("workflows, run history and artifacts survive a page reload and a server restart", async ({ page, studio, project, api }) => {
  await openStudio(page, studio, `workflow/${WORKFLOW}`);
  await setParameter(page, "bootstrap", "resamples", "250");
  const okRun = await runFromEditor(page, WORKFLOW);
  expect((await api.waitForRun(okRun)).run.status).toBe("SUCCEEDED");
  const failedRun = (await api.waitForRun((await api.startRun("failure-demo")).id)).run.id;

  const before = {
    workflow: await api.workflow(WORKFLOW),
    runs: await api.runs(),
    ok: await api.run(okRun),
    failed: await api.run(failedRun),
    artifacts: await api.get<unknown[]>("/api/artifacts"),
  };
  expect(before.runs.map((r) => [r.id, r.status])).toEqual([[failedRun, "FAILED"], [okRun, "SUCCEEDED"]]);

  // 1. Reload the page: the editor comes back from the server, not from browser memory.
  await page.reload();
  await page.getByRole("group", { name: "Node bootstrap", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Inspector" })
    .getByRole("textbox", { name: "Parameter resamples" })).toHaveValue("250");

  // 2. Restart the server process; the new process reads only what is on disk.
  const oldPid = studio.pid;
  await studio.restart();
  expect(studio.pid).not.toBe(oldPid);
  expect(await api.workflow(WORKFLOW)).toEqual(before.workflow);
  expect(await api.runs()).toEqual(before.runs);
  expect(await api.run(okRun)).toEqual(before.ok);
  expect(await api.run(failedRun)).toEqual(before.failed);
  expect(await api.get<unknown[]>("/api/artifacts")).toEqual(before.artifacts);
  expect(project.readWorkflow(WORKFLOW).nodes.find((n) => n.id === "bootstrap")?.params)
    .toEqual({ resamples: 250 });

  await page.reload();
  await page.getByRole("group", { name: "Node bootstrap", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Inspector" })
    .getByRole("textbox", { name: "Parameter resamples" })).toHaveValue("250");

  // Run history, including the failure, is listed after the restart.
  await page.getByRole("navigation", { name: "Main" }).getByRole("button", { name: "Runs & experiments" }).click();
  for (const id of [okRun, failedRun]) {
    await expect(page.getByRole("checkbox", { name: `Select run ${id} for comparison` })).toBeVisible();
  }

  // Artifact metadata and stored bytes are still available and verifiable.
  const report = byNode(before.ok).get("report")!.outputs[0]!;
  await openStudio(page, studio, `artifacts/${report.id}`);
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "report.output" })).toBeVisible();
  await expect(main.getByText(report.id, { exact: true })).toBeVisible();
  await main.getByRole("button", { name: "Verify integrity" }).click();
  await expect(main.getByRole("status")).toHaveText("Stored bytes match the recorded SHA-256.");
  await expect(main.getByRole("button", { name: okRun })).toBeVisible();
  expect(project.hashStoredObject(report.content_hash)).toBe(report.content_hash);
});
