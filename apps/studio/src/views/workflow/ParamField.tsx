import { useEffect, useState } from "react";

import type { PortSpec } from "../../api/types";
import { formatValue } from "../../lib/format";
import { typeLabel } from "../../lib/graph";

interface Props {
  port: PortSpec;
  value: unknown;
  onChange: (value: unknown) => void;
}

const isSet = (value: unknown) => value !== undefined;

/** Text-backed editor that commits on blur/Enter; `parse` returns undefined to clear. */
function TextCommitField({ initial, placeholder, inputMode, parse, multiline, onCommit, label }: {
  initial: string;
  placeholder: string;
  inputMode?: "numeric" | "decimal" | "text";
  parse: (text: string) => { value: unknown } | { error: string };
  multiline?: boolean;
  onCommit: (value: unknown) => void;
  label: string;
}) {
  const [text, setText] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setText(initial), [initial]);
  const commit = () => {
    if (text === initial) return setError(null);
    const parsed = parse(text);
    if ("error" in parsed) return setError(parsed.error);
    setError(null);
    onCommit(parsed.value);
  };
  const common = {
    className: `field ${error ? "border-fail" : ""} ${multiline ? "font-mono text-[12px]" : ""}`,
    value: text,
    placeholder,
    "aria-label": label,
    "aria-invalid": error ? true : undefined,
    onChange: (e: { target: { value: string } }) => setText(e.target.value),
    onBlur: commit,
  };
  return (
    <>
      {multiline
        ? <textarea rows={3} {...common} />
        : <input inputMode={inputMode} {...common}
                 onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />}
      {error && <span className="text-[12px] text-fail">{error}</span>}
    </>
  );
}

export function ParamField({ port, value, onChange }: Props) {
  const fallback = port.has_default ? port.default : undefined;
  const placeholder = port.has_default ? `default: ${port.default_repr ?? formatValue(fallback)}`
    : "required";
  const label = `Parameter ${port.name}`;
  let control;

  switch (port.widget) {
    case "integer":
    case "number":
      control = (
        <TextCommitField label={label} initial={isSet(value) ? String(value) : ""} placeholder={placeholder}
                         inputMode={port.widget === "integer" ? "numeric" : "decimal"}
                         onCommit={onChange}
                         parse={(text) => {
                           if (text.trim() === "") return { value: undefined };
                           const n = Number(text);
                           if (!Number.isFinite(n)) return { error: "Enter a number." };
                           if (port.widget === "integer" && !Number.isInteger(n)) {
                             return { error: "Enter a whole number." };
                           }
                           return { value: n };
                         }} />
      );
      break;
    case "checkbox": {
      const checked = Boolean(isSet(value) ? value : fallback);
      control = (
        <label className="inline-flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
                 aria-label={label} />
          {checked ? "true" : "false"}
        </label>
      );
      break;
    }
    case "select":
      control = (
        <select className="field" aria-label={label}
                value={isSet(value) ? JSON.stringify(value) : ""}
                onChange={(e) => onChange(e.target.value === "" ? undefined : JSON.parse(e.target.value))}>
          <option value="">{placeholder}</option>
          {(port.choices ?? []).map((choice) => (
            <option key={JSON.stringify(choice)} value={JSON.stringify(choice)}>{formatValue(choice)}</option>
          ))}
        </select>
      );
      break;
    case "text":
    case "file":
      control = (
        <TextCommitField label={label} initial={typeof value === "string" ? value : ""}
                         placeholder={port.widget === "file" && !port.has_default
                           ? "path relative to the project root" : placeholder}
                         onCommit={onChange}
                         parse={(text) => ({ value: text === "" ? undefined : text })} />
      );
      break;
    default:
      control = (
        <TextCommitField label={label} multiline initial={isSet(value) ? JSON.stringify(value) : ""}
                         placeholder={placeholder} onCommit={onChange}
                         parse={(text) => {
                           if (text.trim() === "") return { value: undefined };
                           try {
                             return { value: JSON.parse(text) };
                           } catch {
                             return { error: "Enter valid JSON." };
                           }
                         }} />
      );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-medium">
          {port.name}
          {port.required && <span className="text-fail" title="Required"> *</span>}
        </span>
        <span className="flex items-baseline gap-2">
          <span className="font-mono text-[11px] text-ink-faint">{typeLabel(port.type)}</span>
          {isSet(value) && (
            <button type="button" className="text-[11px] text-signal hover:underline"
                    onClick={() => onChange(undefined)}
                    title={port.has_default ? "Use the declared default" : "Clear this value"}>
              reset
            </button>
          )}
        </span>
      </div>
      {control}
      {port.description && <span className="meta">{port.description}</span>}
    </div>
  );
}
