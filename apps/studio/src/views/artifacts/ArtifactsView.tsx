import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, ShieldCheck } from "lucide-react";
import { useState, type ReactNode } from "react";

import { api } from "../../api/client";
import type { ArtifactRecord, VerifyResult } from "../../api/types";
import { EmptyState, ErrorText, Hash, KeyValue, Section, StatusBadge } from "../../components/common";
import { formatBytes, formatTime } from "../../lib/format";
import { useUi } from "../../state/ui";
import { ArtifactPreview } from "./ArtifactPreview";
import { LineageGraph } from "./LineageGraph";

const label = (a: ArtifactRecord) =>
  a.role === "input" ? a.source_uri ?? a.id : `${a.node_id}.${a.port}`;

function ArtifactDetailPanel({ artifactId }: { artifactId: string }) {
  const { openRun, openArtifact, toast } = useUi();
  const [direction, setDirection] = useState<"upstream" | "downstream">("upstream");
  const [verified, setVerified] = useState<VerifyResult | null>(null);
  const detail = useQuery({ queryKey: ["artifact", artifactId], queryFn: () => api.artifact(artifactId) });
  const lineage = useQuery({
    queryKey: ["lineage", artifactId, direction],
    queryFn: () => api.lineage(artifactId, direction),
  });
  const verify = useMutation({
    mutationFn: () => api.verify(artifactId),
    onSuccess: setVerified,
    onError: (error) => toast(error.message),
  });

  if (detail.error) return <EmptyState title="Artifact not found"><ErrorText error={detail.error} /></EmptyState>;
  if (!detail.data) return <p className="meta p-6">Loading artifact…</p>;
  const { artifact, producer, consumers } = detail.data;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-panel">
      <header className="flex items-center gap-3 border-b border-rule px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-[15px] font-semibold">{label(artifact)}</h2>
          <div className="meta">{artifact.kind}, {artifact.media_type}, {formatBytes(artifact.size)}</div>
        </div>
        <div className="ml-auto flex gap-2">
          <button type="button" className="btn" onClick={() => verify.mutate()} disabled={verify.isPending}
                  title="Re-hash the stored bytes and compare with the recorded SHA-256">
            <ShieldCheck size={14} /> Verify integrity
          </button>
          {artifact.stored && (
            <a className="btn" href={api.artifactUrl(artifact.id, true)} download>
              <Download size={14} /> Download
            </a>
          )}
        </div>
      </header>
      {verified && (
        <p className={`border-b border-rule px-4 py-2 text-[13px] ${verified.ok ? "text-ok" : "text-fail"}`}
           role="status">{verified.message}</p>
      )}

      <Section title="Preview">
        <ArtifactPreview detail={detail.data} />
      </Section>

      <Section title="Provenance" actions={
        <div className="flex rounded-md border border-rule text-[12px]" role="group" aria-label="Lineage direction">
          {(["upstream", "downstream"] as const).map((d) => (
            <button key={d} type="button" onClick={() => setDirection(d)} aria-pressed={direction === d}
                    className={`px-2 py-0.5 ${direction === d ? "bg-signal-soft text-signal" : "text-ink-soft"}`}>
              {d === "upstream" ? "What produced this" : "What used this"}
            </button>
          ))}
        </div>}>
        {lineage.error && <ErrorText error={lineage.error} />}
        {lineage.data && (
          <>
            <LineageGraph key={`${artifactId}-${direction}`} lineage={lineage.data} />
            <p className="meta mt-1">
              {lineage.data.nodes.length} records. Solid arrows were observed during execution; dashed
              arrows are inferred from identical content hashes. Click a box to open it.
              {lineage.data.truncated && " The graph was truncated at 500 records."}
            </p>
          </>
        )}
      </Section>

      <Section title="Record">
        <KeyValue rows={[
          ["Artifact id", <span className="hash">{artifact.id}</span>],
          ["SHA-256", <Hash value={artifact.content_hash} length={24} />],
          ["Role", artifact.role === "input" ? "input file read by a node" : "node output"],
          ["Serializer", artifact.serializer ?? "—"],
          ["Python type", artifact.python_type ? <span className="hash">{artifact.python_type}</span> : "—"],
          ["Bytes stored", artifact.stored ? "yes" : "no (hash only)"],
          ["Created", formatTime(artifact.created_at)],
          ["Run", artifact.run_id ? <button type="button" className="font-mono text-[12px] text-signal hover:underline"
                                            onClick={() => openRun(artifact.run_id)}>{artifact.run_id}</button> : "—"],
          ["Produced by", producer ? <span className="flex items-center gap-2">
            <span className="font-mono text-[12px]">{producer.node_id}</span>
            <StatusBadge status={producer.status} cacheHit={producer.cache_hit} /></span> : "—"],
          ...(artifact.reused_from ? [["Reused from", (
            <button type="button" className="font-mono text-[12px] text-signal hover:underline"
                    onClick={() => openArtifact(artifact.reused_from)}>{artifact.reused_from}</button>
          )] as [string, ReactNode]] : []),
          ["Used by", consumers.length ? (
            <ul>{consumers.map((c) => (
              <li key={c.id}>
                <button type="button" className="font-mono text-[12px] text-signal hover:underline"
                        onClick={() => openRun(c.run_id)}>{c.node_id}</button>
                <span className="meta"> in {c.run_id}</span>
              </li>))}
            </ul>) : "nothing yet"],
        ]} />
      </Section>
    </div>
  );
}

export function ArtifactsView() {
  const { artifactId, openArtifact } = useUi();
  const [kind, setKind] = useState("");
  const [role, setRole] = useState("");
  const artifacts = useQuery({
    queryKey: ["artifacts", kind, role],
    queryFn: () => api.artifacts({ kind: kind || undefined, role: role || undefined }),
    refetchInterval: 5000,
  });
  const all = useQuery({ queryKey: ["artifacts", "", ""], queryFn: () => api.artifacts() });
  const kinds = [...new Set((all.data ?? []).map((a) => a.kind))].sort();

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-[420px] shrink-0 flex-col border-r border-rule">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-rule bg-panel px-4">
          <h1 className="text-[15px] font-semibold">Artifacts</h1>
          <select className="field ml-auto w-28" value={kind} onChange={(e) => setKind(e.target.value)}
                  aria-label="Filter by kind">
            <option value="">All kinds</option>
            {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <select className="field w-28" value={role} onChange={(e) => setRole(e.target.value)}
                  aria-label="Filter by role">
            <option value="">Any role</option>
            <option value="output">Outputs</option>
            <option value="input">Input files</option>
          </select>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto bg-panel">
          {artifacts.error && <div className="p-4"><ErrorText error={artifacts.error} /></div>}
          {artifacts.data?.length === 0 && (
            <EmptyState title="No artifacts">Outputs appear here after a workflow runs.</EmptyState>
          )}
          <ul>
            {artifacts.data?.map((a) => (
              <li key={a.id}>
                <button type="button" onClick={() => openArtifact(a.id)}
                        className={`block w-full border-b border-rule-soft px-4 py-2 text-left ${
                          a.id === artifactId ? "bg-signal-soft" : "hover:bg-rule-soft"}`}>
                  <div className="flex justify-between gap-2">
                    <span className="truncate text-[13px] font-medium">{label(a)}</span>
                    <span className="shrink-0 text-[12px] text-ink-faint">{a.kind}</span>
                  </div>
                  <div className="flex justify-between gap-2 text-[12px] text-ink-faint">
                    <span className="font-mono">{a.content_hash.slice(0, 12)}</span>
                    <span>{a.reused_from ? "reused, " : ""}{formatBytes(a.size)}, {formatTime(a.created_at)}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        {artifactId ? <ArtifactDetailPanel key={artifactId} artifactId={artifactId} />
          : <EmptyState title="Select an artifact">
              Every node output and every input file a node read is recorded with its SHA-256 hash and
              the execution that produced or used it.
            </EmptyState>}
      </div>
    </div>
  );
}
