import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

import { pythonExecutable, REPO_ROOT } from "./project";

/** Fail early, with instructions, when the Studio build or the Python package is missing. */
export default function globalSetup(): void {
  const index = path.join(REPO_ROOT, "src", "neuroweave", "server", "static", "index.html");
  if (!existsSync(index)) {
    throw new Error(`The Studio is not built (${index} is missing). Run \`npm run build\` in `
      + "apps/studio, or use `npm run test:e2e`, which builds first.");
  }
  const python = pythonExecutable();
  try {
    execFileSync(python, ["-c", "import neuroweave"], { stdio: "pipe" });
  } catch {
    throw new Error(`${python} cannot import neuroweave. Install it (\`pip install -e .\` in the `
      + "repository root) or point NEUROWEAVE_PYTHON at an interpreter that has it.");
  }
}
