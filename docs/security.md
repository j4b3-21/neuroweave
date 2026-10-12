# Security notes

NeuroWeave v0.2.0 is a single-user, local tool. This document states what it protects
against, what it does not, and how to use it safely.

## The most important fact: node code is not sandboxed

Nodes are ordinary Python functions. When a workflow runs, NeuroWeave imports the project's
node modules and executes them **with your user account's permissions**: they can read and
write any file you can, use the network, and start processes. The worker process used for
Studio runs exists so that a crashing or hanging node cannot take down the server and can be
cancelled; it is **not** a security boundary.

Only configure node modules (Project settings, `nw init -m`) that you would be comfortable
running as a normal Python script. Treat a shared workflow as safe only if its node modules
are.

## Opening a project: trust

Importing a project's node modules runs their code, and that happens as soon as a project is
opened: `nw nodes`, `nw validate`, `nw run` and `nw reproduce` import them, and so does the
Studio when it loads the node catalogue. NeuroWeave therefore asks before importing code from a
project you have not trusted:

- **Projects you create are trusted automatically.** `nw init` records trust when it creates
  `.neuroweave/project.json`, so your own projects never ask.
- **Projects that arrive another way are not.** A cloned repository, an unpacked archive or a
  shared folder already contains `project.json`; `nw init` there does not trust it (it says so).
- **On a terminal, the CLI asks once** ("Do you trust this project's code?", default no) and
  remembers a yes. Without a terminal it refuses and prints the command to run.
- **The Studio opens an untrusted project without importing anything.** Workflows and run
  history can be browsed; the node catalogue explains why it is empty, and starting or
  reproducing a run is refused (HTTP 403). Trusting the project takes effect without
  restarting the Studio.
- **`nw trust`** trusts the current project; **`nw trust --revoke`** withdraws it.
- A project with no node modules imports no project code and needs no trust.

Trust is recorded per resolved project directory in `$NEUROWEAVE_TRUST_FILE`, or
`$XDG_CONFIG_HOME/neuroweave/trusted-projects.json` (default `~/.config/neuroweave/`). The file
lives outside the project, so a project cannot mark itself as trusted. A missing or unreadable
trust file trusts nothing.

What trusting means: you accept that everything in that directory may run with your
permissions, which includes its node modules, any module they import from the project, and
pickled artifacts in its `.neuroweave/` store (see below). Trust is a confirmation step, not
isolation.

Projects created before this check existed ask once, the first time they are opened.

## What is protected

| Threat | Protection |
|---|---|
| Opening a received project silently runs its code | Node modules of an untrusted project are never imported; the CLI asks once on a terminal, the Studio opens it read-only (see above) |
| A project file named like a standard-library module (`argparse.py`, `json.py`) being imported by NeuroWeave's own processes | Catalogue discovery and run workers start with `python -P`, which keeps the project directory off the front of `sys.path`; node modules are still imported from the project root explicitly |
| A `.git/config` shipped inside a project naming a command for `git status` to run (`core.fsmonitor`) | Git is invoked with `core.fsmonitor=false` when a run records the commit and dirty state |
| Other machines on the network calling the API | `nw studio` binds `127.0.0.1` by default; binding another interface prints a warning |
| A malicious website in your browser using DNS rebinding to reach the API | Requests whose `Host` header is not a loopback name are rejected (403) |
| A malicious website making your browser call the API (an `<img>`, a form, `fetch()`) | API requests that the browser labels as cross-site or same-site (`Sec-Fetch-Site`) are rejected (403), including GETs, because loading the catalogue imports project code. In addition, every state-changing `/api` request must carry an `X-NeuroWeave-Client` header, which browsers only send cross-origin after a CORS preflight that the server never grants |
| A crafted artifact (SVG, HTML in Markdown) running script in the Studio | Artifact content is served with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'; …; sandbox`; SVG figures are shown via `<img>` (no script execution); Markdown reports are rendered inside `<iframe sandbox="">` (no scripts, opaque origin) with a CSP that blocks network loads |
| Path traversal via artifact ids or log paths | Artifact hashes are validated as 64 hex characters before touching the filesystem; log paths read by the API and by `nw logs` are resolved and must stay inside `.neuroweave/` |
| Corrupted stored results | Every stored artifact is addressed by its SHA-256; bytes are re-hashed before reuse and on `nw verify`; pickles are loaded only after their hash matches the recorded value. This detects accidental corruption and edits that do not update the database; it does not authenticate who produced the bytes |
| Secrets leaking into run records via the environment | Environment variables are not captured; only Python, platform, Git, package metadata and a pinned lock are stored |
| Lost or half-written project files after a crash | Atomic writes (temporary file, `fsync`, rename) for workflows, snapshots, artifacts and settings; SQLite transactions for history |
| Concurrent editors overwriting each other | Workflow saves from the Studio carry the revision they were based on; stale saves are refused (409) |

## What is not protected (known risks)

- **Trusted code is unrestricted.** Trust only decides *whether* project code runs. Once
  trusted, node modules and everything they import run with your permissions.
- **Pickles in a received workspace.** Objects without a dedicated format are stored with
  Python's pickle, and loading a pickle can execute code. Pickles are loaded only while a run
  executes (`nw run`, `nw reproduce` or a Studio run), when a node's input comes from a stored
  artifact, and running requires a trusted project whenever it has node modules. The SHA-256 check does not help here: whoever wrote the
  `.neuroweave/` directory can write matching bytes and database rows, and a planted pickle can
  be picked up through the cache. Treat a received `.neuroweave/` directory exactly like
  received code. The server never unpickles.
- **File parameters can name any readable path.** A `Path` parameter may be absolute, start
  with `~` or contain `..`. When a workflow runs, the file is hashed and, up to
  `max_input_snapshot_bytes` (50 MB by default), copied into the artifact store. A received
  workflow could therefore point a trusted node at, say, a key file and copy it into
  `.neuroweave/`. Review the file parameters of imported workflows before running them.
- **Run records describe your machine.** The environment record contains the Python
  executable path (usually including your user name), platform and installed packages; input
  artifacts outside the project are recorded by absolute path; the Git branch and commit are
  stored. Node logs contain whatever the node printed, including any secrets it printed.
  Review `.neuroweave/` before sharing it.
- **Git can still run repository-configured commands.** `git status` may run clean filters
  configured in a shipped `.git/config`. This happens only while a run executes, which
  requires trust for any project with node modules. NeuroWeave never runs Git for an
  untrusted project with node modules.
- **Trust is keyed by directory path.** If you trusted a directory and later unpack something
  different into the same path, it is trusted. Revoke trust (`nw trust --revoke`) for
  directories you reuse for downloads.
- **Other local software.** Any process running on your machine can call the local API;
  there is no authentication or token. Do not run `nw studio` on a shared multi-user host.
- **Browsers that do not send `Sec-Fetch-Site`.** Current Chromium, Firefox and Safari send
  it; for older browsers only the Host and custom-header checks apply, and a cross-site GET
  could make the server load the catalogue of an already-trusted project.
- **Binding to a public interface.** `nw studio --host 0.0.0.0` exposes an unauthenticated
  API that can execute your node code. Don't do this; use an SSH tunnel if you need remote
  access.
- **Denial of service by node code** (memory exhaustion, disk filling). There are no
  resource limits.
- **Supply-chain risks** in node modules and their dependencies.
- **Isolated reproduction installs packages.** `nw reproduce --isolated` (and the Studio's
  "Reproduce in a rebuilt environment") runs `uv pip install` against the package index using
  the run's recorded lock. It requires a trusted project, refuses source builds by default
  (`--allow-build` lifts that), and re-reads any `file://` local paths named in the lock.
  Treat a received lock the way you would treat a received `requirements.txt`: only rebuild
  environments for runs you trust. This is not a sandbox; node code in the rebuilt
  environment still runs with your permissions.

## Requirements for future isolation (not implemented)

NeuroWeave does not sandbox node code, and nothing in this release should be read as a
sandbox. Running untrusted workflows safely would need, at minimum:

1. Execution in an OS-level boundary (container, VM or a platform sandbox) with no access to
   the user's home directory, only to declared inputs and a scratch output directory.
2. No network by default, with per-workflow opt-in.
3. CPU, memory, disk and wall-clock limits enforced by that boundary, not by the worker.
4. Artifacts crossing the boundary only in data formats that cannot execute on load (no
   pickle), checked against an allowlist of serializers.
5. File parameters restricted to the project or to explicitly granted paths.
6. A per-session API token for the Studio so other local processes cannot drive it.
7. A scrubbing step (paths, user names, logs) before a workspace is exported or shared.

## Reporting

This is research software without a formal security process yet. Report issues privately to
the repository owner rather than in a public issue.
