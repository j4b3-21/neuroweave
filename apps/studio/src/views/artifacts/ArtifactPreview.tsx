import { useQuery } from "@tanstack/react-query";
import { marked } from "marked";
import { useMemo } from "react";

import { api } from "../../api/client";
import type { ArtifactDetail } from "../../api/types";
import { ErrorText } from "../../components/common";
import { formatBytes } from "../../lib/format";

const TABLE_ROW_LIMIT = 200;

// Rendered in an <iframe sandbox=""> (no scripts, opaque origin); the CSP additionally blocks
// any network fetches a report might attempt, e.g. remote images.
const REPORT_SHELL = (body: string) => `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<style>
body{font:14px/1.55 "IBM Plex Sans",system-ui,sans-serif;color:#18222f;margin:20px 28px;max-width:860px}
h1,h2,h3{line-height:1.25;margin:1.2em 0 .5em}h1{font-size:22px}h2{font-size:18px}h3{font-size:15px}
table{border-collapse:collapse;margin:.8em 0}th,td{border-bottom:1px solid #d9e0e6;padding:4px 10px;text-align:left}
th{color:#4a5868;font-weight:500}code{font:12px "IBM Plex Mono",monospace;background:#f3f5f7;padding:1px 4px;border-radius:3px}
pre{background:#f3f5f7;padding:10px;overflow:auto}svg,img{max-width:100%;height:auto}
</style></head><body>${body}</body></html>`;

function TablePreview({ text }: { text: string }) {
  const table = useMemo(() => JSON.parse(text) as { columns: string[]; rows: unknown[][] }, [text]);
  return (
    <div>
      <p className="meta mb-1">
        {table.rows.length} rows, {table.columns.length} columns
        {table.rows.length > TABLE_ROW_LIMIT && `; showing the first ${TABLE_ROW_LIMIT}`}
      </p>
      <div className="max-h-[480px] overflow-auto rounded-md border border-rule">
        <table className="data-table">
          <thead className="sticky top-0 bg-panel">
            <tr>{table.columns.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {table.rows.slice(0, TABLE_ROW_LIMIT).map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} className={`font-mono text-[12px] ${cell === null ? "text-ink-faint" : ""}`}>
                    {cell === null ? "null" : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ArtifactPreview({ detail }: { detail: ArtifactDetail }) {
  const { artifact, previewable } = detail;
  const isSvg = artifact.media_type === "image/svg+xml";
  const text = useQuery({
    queryKey: ["artifact-text", artifact.id],
    queryFn: () => api.artifactText(artifact.id),
    enabled: previewable && !isSvg,
    staleTime: Infinity,
  });

  if (!artifact.stored) {
    return <p className="meta">Only the hash of this input was recorded (it exceeded the project's
      snapshot size limit or is a directory manifest), so there is nothing to preview.</p>;
  }
  if (!previewable) {
    return <p className="meta">No preview for {artifact.media_type} ({formatBytes(artifact.size)}).
      Download the file to inspect it.</p>;
  }
  if (isSvg) {
    return (
      <div className="rounded-md border border-rule bg-white p-3">
        <img src={api.artifactUrl(artifact.id)} alt={`Figure ${artifact.port ?? artifact.id}`}
             className="mx-auto max-h-[520px] max-w-full" />
      </div>
    );
  }
  if (text.error) return <ErrorText error={text.error} />;
  if (text.data === undefined) return <p className="meta">Loading preview…</p>;

  try {
    switch (artifact.media_type) {
      case "application/vnd.neuroweave.table+json":
        return <TablePreview text={text.data} />;
      case "text/markdown":
        return (
          <iframe title="Report preview" sandbox="" className="report-frame rounded-md border border-rule"
                  srcDoc={REPORT_SHELL(marked.parse(text.data, { async: false }))} />
        );
      case "application/json":
        return <pre className="max-h-[480px] overflow-auto rounded-md bg-canvas p-3 font-mono text-[12px]">
          {JSON.stringify(JSON.parse(text.data), null, 2)}</pre>;
      default:
        return <pre className="max-h-[480px] overflow-auto rounded-md bg-canvas p-3 font-mono text-[12px] whitespace-pre-wrap">
          {text.data}</pre>;
    }
  } catch (error) {
    return <ErrorText error={new Error(`Could not render this artifact: ${String(error)}`)} />;
  }
}
