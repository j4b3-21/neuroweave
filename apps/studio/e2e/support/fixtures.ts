import { expect, type Page, test as base } from "@playwright/test";

import { Api } from "./api";
import { Project, StudioServer } from "./project";

interface Fixtures {
  project: Project;
  studio: StudioServer;
  api: Api;
}

const isLocal = (url: string) => {
  if (!/^https?:/.test(url)) return true; // data:, blob:, about:
  const { hostname } = new URL(url);
  return hostname === "127.0.0.1" || hostname === "localhost";
};

export const test = base.extend<Fixtures>({
  project: async ({}, use) => {
    const project = new Project();
    await use(project);
    if (!process.env.NW_E2E_KEEP) project.remove();
  },

  studio: async ({ project }, use, testInfo) => {
    const studio = new StudioServer(project);
    await studio.start();
    try {
      await use(studio);
    } finally {
      await studio.stop();
      if (testInfo.status !== testInfo.expectedStatus) {
        await testInfo.attach("nw-studio.log", { body: studio.log, contentType: "text/plain" });
      }
    }
  },

  api: async ({ request, studio }, use) => {
    await use(new Api(request, () => studio.url));
  },

  // Guard rails for every page: no request may leave the machine, and an uncaught exception in
  // the Studio fails the test. Pre-dismiss the first-visit welcome dialog so other specs stay
  // focused on their own flows (tour.spec.ts covers the dialog itself).
  page: async ({ page }, use) => {
    const external: string[] = [];
    const pageErrors: string[] = [];
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem("neuroweave.tour.welcome", "1");
      } catch {
        /* ignore */
      }
    });
    await page.route((url) => !isLocal(url.href), (route) => {
      external.push(route.request().url());
      return route.abort();
    });
    page.on("pageerror", (error) => pageErrors.push(`${error.name}: ${error.message}`));
    await use(page);
    expect(external, "requests to non-local hosts").toEqual([]);
    expect(pageErrors, "uncaught exceptions in the Studio").toEqual([]);
  },
});

export { expect };

/** Open a Studio route (URL hash) on the test's server and wait for the shell to load. */
export async function openStudio(page: Page, studio: StudioServer, hash: string): Promise<void> {
  await page.goto(`${studio.url}/#/${hash}`);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}
