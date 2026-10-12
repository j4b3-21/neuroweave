/**
 * Disposable NeuroWeave projects and `nw studio` server processes for the browser tests.
 *
 * Every test gets its own temporary directory (a copy of examples/research_demo plus the
 * fixtures in e2e/fixtures), initialised and populated through the real `nw` CLI, and its own
 * server on a free loopback port. Nothing outside the temporary directory is read or written.
 */
import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

export const STUDIO_DIR = path.resolve(import.meta.dirname, "../..");
export const REPO_ROOT = path.resolve(STUDIO_DIR, "../..");
const DEMO_DIR = path.join(REPO_ROOT, "examples", "research_demo");
const FIXTURES_DIR = path.join(STUDIO_DIR, "e2e", "fixtures");
const FIXTURE_WORKFLOWS = ["failure-demo.json", "nondeterministic.json"];

/** Interpreter with `neuroweave` installed: $NEUROWEAVE_PYTHON, the repo's .venv, or python3. */
export function pythonExecutable(): string {
  if (process.env.NEUROWEAVE_PYTHON) return process.env.NEUROWEAVE_PYTHON;
  const venv = path.join(REPO_ROOT, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

/** Environment for NeuroWeave processes of a test project; trust decisions stay in its temp dir. */
function nwEnv(root: string): NodeJS.ProcessEnv {
  return {
    ...process.env,
    PYTHONDONTWRITEBYTECODE: "1",
    NEUROWEAVE_TRUST_FILE: path.join(path.dirname(root), "trusted-projects.json"),
  };
}

function nw(root: string, ...args: string[]): string {
  return execFileSync(pythonExecutable(), ["-m", "neuroweave.cli", "--project", root, ...args], {
    cwd: root, encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"], env: nwEnv(root),
  });
}

export interface WorkflowFile {
  id: string;
  name: string;
  nodes: { id: string; type: string; params: Record<string, unknown> }[];
  edges: { source: string; source_port: string; target: string; target_port: string }[];
}

export class Project {
  readonly tempDir: string;
  readonly root: string;

  constructor() {
    this.tempDir = mkdtempSync(path.join(os.tmpdir(), "nw-e2e-"));
    this.root = path.join(this.tempDir, "project");
    cpSync(DEMO_DIR, this.root, {
      recursive: true,
      filter: (source) => !/[/\\](\.neuroweave|__pycache__)([/\\]|$)/.test(source),
    });
    cpSync(path.join(FIXTURES_DIR, "e2e_nodes.py"), path.join(this.root, "e2e_nodes.py"));
    nw(this.root, "init", "--name", "E2E project", "-m", "demo_nodes", "-m", "e2e_nodes");
    nw(this.root, "workflows", "import", path.join(this.root, "workflow.json"));
    for (const file of FIXTURE_WORKFLOWS) {
      nw(this.root, "workflows", "import", path.join(FIXTURES_DIR, file));
    }
  }

  /** `nw trust` / `nw trust --revoke`: a project created by `nw init` starts out trusted. */
  setTrusted(trusted: boolean): void {
    nw(this.root, "trust", ...(trusted ? [] : ["--revoke"]));
  }

  get workspaceDir(): string {
    return path.join(this.root, ".neuroweave");
  }

  /** The workflow definition as stored on disk (what the Studio saved). */
  readWorkflow(id: string): WorkflowFile {
    return JSON.parse(readFileSync(path.join(this.workspaceDir, "workflows", `${id}.json`), "utf-8"));
  }

  snapshotExists(hash: string): boolean {
    return existsSync(path.join(this.workspaceDir, "snapshots", `${hash}.json`));
  }

  objectPath(contentHash: string): string {
    return path.join(this.workspaceDir, "artifacts", "objects", contentHash.slice(0, 2), contentHash);
  }

  /** SHA-256 of the bytes in the content-addressed store, computed independently of NeuroWeave. */
  hashStoredObject(contentHash: string): string {
    return createHash("sha256").update(readFileSync(this.objectPath(contentHash))).digest("hex");
  }

  remove(): void {
    rmSync(this.tempDir, { recursive: true, force: true });
  }
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address() as net.AddressInfo;
      server.close(() => resolve(port));
    });
  });
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** `nw studio --no-open` for one project. Ready once /api/health answers and the UI is served. */
export class StudioServer {
  private process: ChildProcess | null = null;
  private output = "";
  port = 0;

  constructor(readonly project: Project) {}

  get url(): string {
    return `http://127.0.0.1:${this.port}`;
  }

  get log(): string {
    return this.output;
  }

  get pid(): number | undefined {
    return this.process?.pid;
  }

  async start(timeoutMs = 30_000): Promise<void> {
    if (!this.port) this.port = await freePort();
    const child = spawn(pythonExecutable(), [
      "-m", "neuroweave.cli", "--project", this.project.root, "studio", "--no-open",
      "--port", String(this.port),
    ], { cwd: this.project.root, env: nwEnv(this.project.root) });
    this.process = child;
    child.stdout?.on("data", (chunk) => { this.output += chunk; });
    child.stderr?.on("data", (chunk) => { this.output += chunk; });

    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (child.exitCode !== null) {
        throw new Error(`nw studio exited with code ${child.exitCode}:\n${this.output}`);
      }
      try {
        const health = await fetch(`${this.url}/api/health`);
        if (health.ok) {
          const index = await (await fetch(`${this.url}/`)).text();
          if (!index.includes('id="root"')) {
            throw new Error("nw studio is serving the API but not the Studio UI. Build it first: "
              + "npm --prefix apps/studio run build");
          }
          return;
        }
      } catch (error) {
        if (error instanceof Error && error.message.includes("Build it first")) throw error;
      }
      await sleep(100);
    }
    throw new Error(`nw studio did not become ready within ${timeoutMs} ms:\n${this.output}`);
  }

  async stop(timeoutMs = 10_000): Promise<void> {
    const child = this.process;
    this.process = null;
    if (!child || child.exitCode !== null || child.signalCode !== null) return;
    const exited = new Promise<void>((resolve) => child.once("exit", () => resolve()));
    child.kill("SIGTERM");
    const timer = setTimeout(() => child.kill("SIGKILL"), timeoutMs);
    await exited;
    clearTimeout(timer);
  }

  /** Stop the server process and start a new one for the same project on the same port. */
  async restart(): Promise<void> {
    await this.stop();
    await this.start();
  }
}
