import { useQuery } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useMemo, useState, type CSSProperties } from "react";

import { api } from "../api/client";
import { useUi } from "../state/ui";
import { dismissWelcome, markTourCompleted, welcomeDismissed } from "./storage";
import { stepsFor, type TourStep } from "./steps";

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

function measure(target?: string): Rect | null {
  if (!target) return null;
  const el = document.querySelector(`[data-tour="${CSS.escape(target)}"]`);
  if (!(el instanceof HTMLElement)) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null;
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

function useStepRect(step: TourStep | undefined): Rect | null {
  const [rect, setRect] = useState<Rect | null>(null);
  useLayoutEffect(() => {
    const update = () => setRect(measure(step?.target));
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    // Targets often appear after a view switch; poll briefly until found.
    const timer = window.setInterval(update, 200);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      window.clearInterval(timer);
    };
  }, [step?.id, step?.target]);
  return rect;
}

export function Tour() {
  const active = useUi((s) => s.tourActive);
  const index = useUi((s) => s.tourStep);
  const nextTour = useUi((s) => s.nextTour);
  const prevTour = useUi((s) => s.prevTour);
  const stopTour = useUi((s) => s.stopTour);
  const setView = useUi((s) => s.setView);
  const select = useUi((s) => s.select);
  const openRun = useUi((s) => s.openRun);
  const project = useQuery({ queryKey: ["project"], queryFn: api.project });
  const steps = useMemo(() => stepsFor(Boolean(project.data?.tutorial)), [project.data?.tutorial]);
  const step = steps[index];
  const runs = useQuery({
    queryKey: ["runs", "all"],
    queryFn: () => api.runs(),
    enabled: active && step?.id === "reproduce",
  });
  const rect = useStepRect(step);

  useEffect(() => {
    if (!active || !step) return;
    if (step.view) setView(step.view);
    if (step.selectNode) select({ kind: "node", id: step.selectNode });
    if (step.id === "reproduce" && runs.data?.[0]) openRun(runs.data[0].id);
  }, [active, step, setView, select, openRun, runs.data]);

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        stopTour();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        if (index >= steps.length - 1) {
          markTourCompleted();
          stopTour();
        } else {
          nextTour(steps.length);
        }
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        prevTour();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, index, steps.length, nextTour, prevTour, stopTour]);

  if (!active || !step) return null;

  const pad = 8;
  const spotlight = rect
    ? {
        top: Math.max(0, rect.top - pad),
        left: Math.max(0, rect.left - pad),
        width: rect.width + pad * 2,
        height: rect.height + pad * 2,
      }
    : null;

  const popoverStyle: CSSProperties = spotlight
    ? {
        top: Math.min(window.innerHeight - 220, spotlight.top + spotlight.height + 12),
        left: Math.min(window.innerWidth - 360, Math.max(16, spotlight.left)),
      }
    : { top: "30%", left: "50%", transform: "translateX(-50%)" };

  const finish = () => {
    markTourCompleted();
    stopTour();
  };

  return (
    <div className="pointer-events-none fixed inset-0 z-[80]" role="dialog" aria-modal="true"
         aria-labelledby="nw-tour-title" data-testid="tour-overlay">
      <div className="absolute inset-0 bg-ink/40" />
      {spotlight && (
        <div className="absolute rounded-md ring-2 ring-signal ring-offset-2 ring-offset-transparent"
             style={{
               top: spotlight.top, left: spotlight.left,
               width: spotlight.width, height: spotlight.height,
               boxShadow: "0 0 0 9999px rgba(15, 23, 42, 0.45)",
             }} />
      )}
      <div className="pointer-events-auto absolute w-[340px] max-w-[calc(100vw-2rem)] rounded-lg border border-rule bg-panel p-4 shadow-lg"
           style={popoverStyle}>
        <div className="meta mb-1">{index + 1} of {steps.length}</div>
        <h2 id="nw-tour-title" className="text-[15px] font-semibold">{step.title}</h2>
        <p className="mt-1 text-[13px] text-ink-soft">{step.body}</p>
        {!spotlight && step.target && (
          <p className="meta mt-2">That control is not on screen right now; the tip is shown here instead.</p>
        )}
        <div className="mt-3 flex items-center gap-2">
          <button type="button" className="btn btn-quiet" onClick={() => {
            markTourCompleted();
            stopTour();
          }}>Skip</button>
          <div className="ml-auto flex gap-2">
            <button type="button" className="btn" disabled={index === 0} onClick={prevTour}>Back</button>
            {index >= steps.length - 1 ? (
              <button type="button" className="btn btn-primary" onClick={finish}>Done</button>
            ) : (
              <button type="button" className="btn btn-primary" onClick={() => nextTour(steps.length)}>
                Next
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function WelcomeDialog() {
  const [open, setOpen] = useState(false);
  const startTour = useUi((s) => s.startTour);
  const project = useQuery({ queryKey: ["project"], queryFn: api.project });

  useEffect(() => {
    const hash = window.location.hash;
    const tourHash = hash === "#tour" || hash === "#/tour"
      || hash.startsWith("#tour=") || hash.startsWith("#/tour=");
    if (tourHash) {
      startTour(0);
      window.history.replaceState(null, "", "#/workflow");
      return;
    }
    if (!welcomeDismissed()) setOpen(true);
  }, [startTour]);

  if (!open || !project.data) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-ink/40 p-4"
         role="dialog" aria-modal="true" aria-labelledby="nw-welcome-title"
         data-testid="welcome-dialog">
      <div className="w-full max-w-md rounded-lg border border-rule bg-panel p-5 shadow-lg">
        <h2 id="nw-welcome-title" className="text-[16px] font-semibold">Welcome to NeuroWeave Studio</h2>
        <p className="mt-2 text-[13px] text-ink-soft">
          Take a short tour of the editor, runs, reproduction and artifacts. You can reopen it
          later from Help.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="btn btn-quiet" onClick={() => {
            dismissWelcome();
            setOpen(false);
          }}>Not now</button>
          <button type="button" className="btn btn-primary" onClick={() => {
            dismissWelcome();
            setOpen(false);
            startTour(0);
          }}>Take the tour</button>
        </div>
      </div>
    </div>
  );
}
