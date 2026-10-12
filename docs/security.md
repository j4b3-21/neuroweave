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

## What is protected

| Threat | Protection |
|---|---|
| Other machines on the network calling the API | `nw studio` binds `127.0.0.1` by default; binding another interface prints a warning |
| A malicious website in your browser using DNS rebinding to reach the API | Requests whose `Host` header is not a loopback name are rejected (403) |
| A malicious website submitting forms or simple cross-site requests that change state | Every state-changing `/api` request must carry an `X-NeuroWeave-Client` header; browsers only send custom headers cross-origin after a CORS preflight, and the server never grants CORS |
| A crafted artifact (SVG, HTML in Markdown) running script in the Studio | Artifact content is served with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'; …; sandbox`; SVG figures are shown via `<img>` (no script execution); Markdown reports are rendered inside `<iframe sandbox="">` (no scripts, opaque origin) with a CSP that blocks network loads |
| Path traversal via artifact ids or log paths | Artifact hashes are validated as 64 hex characters before touching the filesystem; log paths are resolved and must stay inside `.neuroweave/` |
| Tampered or corrupted stored results | Every stored artifact is addressed by its SHA-256; bytes are re-hashed before reuse and on `nw verify`; pickles are loaded only after their hash matches the recorded value |
| Secrets leaking into run records | Environment variables are not captured; only Python, platform, Git and package metadata is stored |
| Lost or half-written project files after a crash | Atomic writes (temporary file, `fsync`, rename) for workflows, snapshots, artifacts and settings; SQLite transactions for history |
| Concurrent editors overwriting each other | Workflow saves from the Studio carry the revision they were based on; stale saves are refused (409) |

## What is not protected

- **Other local software.** Any process running on your machine can call the local API;
  there is no authentication or token. Do not run `nw studio` on a shared multi-user host.
- **Binding to a public interface.** `nw studio --host 0.0.0.0` exposes an unauthenticated
  API that can execute your node code. Don't do this; use an SSH tunnel if you need remote
  access.
- **Untrusted pickles from elsewhere.** Artifacts are only produced by your own runs, but if
  someone gives you a `.neuroweave/` directory, its pickled artifacts would execute code when
  loaded. Treat a received workspace like received code.
- **Denial of service by node code** (memory exhaustion, disk filling). There are no
  resource limits.
- **Supply-chain risks** in node modules and their dependencies.

## Reporting

This is research software without a formal security process yet. Report issues privately to
the repository owner rather than in a public issue.
