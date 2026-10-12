import { realpathSync } from "node:fs";

import { expect, openStudio, test } from "./support/fixtures";

test("Studio is served for a disposable project", async ({ page, studio, project, api }) => {
  await openStudio(page, studio, "project");

  const nav = page.getByRole("navigation", { name: "Main" });
  for (const name of ["Rainfall and crop yield", "Failure demo", "Nondeterministic"]) {
    await expect(nav.getByRole("button", { name })).toBeVisible();
  }

  // The server works on the temporary copy, never on the repository or a user project.
  const info = await api.get<{ root: string; name: string; node_modules: string[] }>("/api/project");
  expect(info.root).toBe(realpathSync(project.root));
  expect(info.node_modules).toEqual(["demo_nodes", "e2e_nodes"]);
  await expect(page.getByText(info.root)).toBeVisible();
  await expect(page.getByText("E2E project").first()).toBeVisible();
});
