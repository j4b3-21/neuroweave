import { expect, openStudio, test } from "./support/fixtures";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

/**
 * Undo the shared fixture's welcome pre-dismiss for the first document load only.
 * sessionStorage keeps the clear from repeating on reload so "Not now" can persist.
 */
async function clearWelcome(page: import("@playwright/test").Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      if (window.sessionStorage.getItem("nw-e2e-welcome-cleared")) return;
      window.localStorage.removeItem("neuroweave.tour.welcome");
      window.localStorage.removeItem("neuroweave.tour.completed");
      window.sessionStorage.setItem("nw-e2e-welcome-cleared", "1");
    } catch {
      /* ignore */
    }
  });
}

function markTutorial(projectRoot: string): void {
  const configPath = path.join(projectRoot, ".neuroweave", "project.json");
  const config = JSON.parse(readFileSync(configPath, "utf-8")) as Record<string, unknown>;
  config.tutorial = true;
  writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`);
}

test.describe("guided tour", () => {
  test("#tour starts the tour", async ({ page, studio, project }) => {
    markTutorial(project.root);
    await openStudio(page, studio, "tour=1");
    const overlay = page.getByTestId("tour-overlay");
    await expect(overlay).toBeVisible();
    await expect(overlay.getByRole("heading", { name: "Welcome to NeuroWeave Studio" })).toBeVisible();
    await expect(overlay.getByText("1 of")).toBeVisible();
  });

  test("Next and Back move between steps", async ({ page, studio }) => {
    await openStudio(page, studio, "tour");
    const overlay = page.getByTestId("tour-overlay");
    await expect(overlay).toBeVisible();
    await overlay.getByRole("button", { name: "Next" }).click();
    await expect(overlay.getByRole("heading", { name: "Your workflows" })).toBeVisible();
    await expect(page.locator("[data-tour=\"workflows\"]")).toBeVisible();
    await overlay.getByRole("button", { name: "Next" }).click();
    await expect(overlay.getByRole("heading", { name: "Node palette" })).toBeVisible();
    await expect(page.locator("[data-tour=\"palette\"]")).toBeVisible();
    await overlay.getByRole("button", { name: "Back" }).click();
    await expect(overlay.getByRole("heading", { name: "Your workflows" })).toBeVisible();
  });

  test("Skip persists after a reload", async ({ page, studio }) => {
    await openStudio(page, studio, "tour");
    const overlay = page.getByTestId("tour-overlay");
    await expect(overlay).toBeVisible();
    await overlay.getByRole("button", { name: "Skip" }).click();
    await expect(overlay).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.getByTestId("tour-overlay")).toHaveCount(0);
    await expect(page.getByTestId("welcome-dialog")).toHaveCount(0);
  });

  test("Help reopens the tour", async ({ page, studio }) => {
    await openStudio(page, studio, "workflow");
    await expect(page.getByTestId("tour-overlay")).toHaveCount(0);
    await page.getByRole("navigation", { name: "Main" })
      .getByRole("button", { name: "Take the tour" }).click();
    await expect(page.getByTestId("tour-overlay")).toBeVisible();
    await expect(page.getByTestId("tour-overlay")
      .getByRole("heading", { name: "Welcome to NeuroWeave Studio" })).toBeVisible();
  });
});

test.describe("welcome dialog", () => {
  test("appears only on the first visit", async ({ page, studio }) => {
    await clearWelcome(page);
    await page.goto(`${studio.url}/#/workflow`);
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    const welcome = page.getByTestId("welcome-dialog");
    await expect(welcome).toBeVisible();
    await welcome.getByRole("button", { name: "Not now" }).click();
    await expect(welcome).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.getByTestId("welcome-dialog")).toHaveCount(0);
  });

  test("Take the tour starts the overlay", async ({ page, studio }) => {
    await clearWelcome(page);
    await page.goto(`${studio.url}/#/workflow`);
    const welcome = page.getByTestId("welcome-dialog");
    await expect(welcome).toBeVisible();
    await welcome.getByRole("button", { name: "Take the tour" }).click();
    await expect(welcome).toHaveCount(0);
    await expect(page.getByTestId("tour-overlay")).toBeVisible();
  });
});
