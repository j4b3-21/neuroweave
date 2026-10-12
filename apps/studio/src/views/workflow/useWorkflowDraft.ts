import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { LoadedWorkflow, ValidationReport, Workflow } from "../../api/types";

export type SaveState = "idle" | "dirty" | "saving" | "saved" | "error" | "conflict";

const SAVE_DELAY_MS = 600;

/**
 * Local editing copy of a persisted workflow. Every change is written back to the server
 * (debounced) with the revision it was based on; the server refuses the write if someone else
 * saved in between, and its response carries the kernel's validation report for that exact
 * version, so the editor never shows issues computed from a graph that was not saved.
 */
export function useWorkflowDraft(workflowId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["workflow", workflowId],
    queryFn: () => api.workflow(workflowId),
    staleTime: Infinity,
  });
  const [draft, setDraft] = useState<Workflow | null>(null);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const draftRef = useRef<Workflow | null>(null);
  const savedRef = useRef<Workflow | null>(null);
  const revisionRef = useRef<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const inFlight = useRef<Promise<unknown> | null>(null);
  const conflictRef = useRef(false);

  const adopt = useCallback((loaded: LoadedWorkflow) => {
    conflictRef.current = false;
    draftRef.current = loaded.workflow;
    savedRef.current = loaded.workflow;
    revisionRef.current = loaded.revision;
    setDraft(loaded.workflow);
    setSaveState("idle");
    setSaveError(null);
    api.validate(loaded.workflow).then(setValidation, () => undefined);
  }, []);

  useEffect(() => {
    if (query.data && !draftRef.current) adopt(query.data);
  }, [query.data, adopt]);

  const flush = useCallback(async (): Promise<boolean> => {
    window.clearTimeout(timer.current);
    for (;;) {
      if (inFlight.current) {
        await inFlight.current.catch(() => undefined);
        continue;
      }
      if (conflictRef.current) return false;
      const current = draftRef.current;
      if (!current || current === savedRef.current) return true;
      setSaveState("saving");
      const attempt = api.saveWorkflow(current, revisionRef.current);
      inFlight.current = attempt;
      try {
        const result = await attempt;
        savedRef.current = current;
        revisionRef.current = result.revision;
        setValidation(result.validation);
        setSaveError(null);
        setSaveState(draftRef.current === current ? "saved" : "dirty");
        queryClient.setQueryData<LoadedWorkflow>(["workflow", current.id],
          { workflow: current, revision: result.revision });
        void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      } catch (error) {
        const conflict = error instanceof ApiError && error.status === 409;
        setSaveError(error instanceof Error ? error.message : String(error));
        setSaveState(conflict ? "conflict" : "error");
        // Never autosave onto a version this editor has not seen; the user must reload.
        conflictRef.current = conflict;
        return false;
      } finally {
        inFlight.current = null;
      }
    }
  }, [queryClient]);

  /** Apply an edit. `defer` updates the draft without scheduling a save (e.g. mid-drag). */
  const update = useCallback((edit: (workflow: Workflow) => Workflow, mode: "save" | "defer" = "save") => {
    const previous = draftRef.current;
    if (!previous || conflictRef.current) return;
    const next = edit(previous);
    if (next === previous) return;
    draftRef.current = next;
    setDraft(next);
    setSaveState("dirty");
    if (mode === "save") {
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => void flush(), SAVE_DELAY_MS);
    }
  }, [flush]);

  /** Discard local changes and load the stored version. */
  const reload = useCallback(async () => {
    window.clearTimeout(timer.current);
    const loaded = await queryClient.fetchQuery({
      queryKey: ["workflow", workflowId], queryFn: () => api.workflow(workflowId), staleTime: 0,
    });
    adopt(loaded);
  }, [adopt, queryClient, workflowId]);

  useEffect(() => () => void flush(), [flush]);

  return {
    draft, validation, setValidation, saveState, saveError, update, flush, reload,
    loadError: query.error,
  };
}
