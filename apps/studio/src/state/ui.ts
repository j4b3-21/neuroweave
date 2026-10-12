import { create } from "zustand";

export type View = "workflow" | "runs" | "artifacts" | "nodes" | "project";
export type Selection = { kind: "node"; id: string } | { kind: "edge"; key: string } | null;
export type BottomTab = "problems" | "run" | "logs";

export interface Toast {
  id: number;
  tone: "error" | "info";
  message: string;
}

interface UiState {
  view: View;
  workflowId: string | null;
  runId: string | null;
  compareIds: string[];
  artifactId: string | null;
  selection: Selection;
  bottomOpen: boolean;
  bottomTab: BottomTab;
  toasts: Toast[];
  tourActive: boolean;
  tourStep: number;
  openWorkflow: (id: string | null) => void;
  openRun: (id: string | null) => void;
  openArtifact: (id: string | null) => void;
  setView: (view: View) => void;
  toggleCompare: (id: string) => void;
  select: (selection: Selection) => void;
  showBottom: (tab: BottomTab) => void;
  setBottomOpen: (open: boolean) => void;
  toast: (message: string, tone?: Toast["tone"]) => void;
  dismiss: (id: number) => void;
  startTour: (step?: number) => void;
  stopTour: () => void;
  nextTour: (total: number) => void;
  prevTour: () => void;
}

let toastCounter = 0;

function fromHash(): Partial<UiState> {
  const raw = window.location.hash.replace(/^#\/?/, "");
  if (raw === "tour" || raw.startsWith("tour=")) {
    return { view: "workflow", tourActive: true, tourStep: 0 };
  }
  const [view, id] = raw.split("/").map(decodeURIComponent);
  switch (view) {
    case "workflow":
      return { view: "workflow", workflowId: id || null };
    case "runs":
      return { view: "runs", runId: id || null };
    case "artifacts":
      return { view: "artifacts", artifactId: id || null };
    case "nodes":
    case "project":
      return { view };
    default:
      return {};
  }
}

export const useUi = create<UiState>((set) => ({
  view: "workflow",
  workflowId: null,
  runId: null,
  compareIds: [],
  artifactId: null,
  selection: null,
  bottomOpen: false,
  bottomTab: "problems",
  toasts: [],
  tourActive: false,
  tourStep: 0,
  ...fromHash(),
  openWorkflow: (id) => set({ view: "workflow", workflowId: id, selection: null }),
  openRun: (id) => set({ view: "runs", runId: id }),
  openArtifact: (id) => set({ view: "artifacts", artifactId: id }),
  setView: (view) => set({ view }),
  toggleCompare: (id) =>
    set((s) => ({
      compareIds: s.compareIds.includes(id)
        ? s.compareIds.filter((x) => x !== id)
        : [...s.compareIds, id].slice(-2),
    })),
  select: (selection) => set({ selection }),
  showBottom: (tab) => set({ bottomOpen: true, bottomTab: tab }),
  setBottomOpen: (open) => set({ bottomOpen: open }),
  toast: (message, tone = "error") => {
    const id = ++toastCounter;
    set((s) => ({ toasts: [...s.toasts, { id, tone, message }] }));
    window.setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
      tone === "error" ? 8000 : 4000);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  startTour: (step = 0) => set({ tourActive: true, tourStep: step }),
  stopTour: () => set({ tourActive: false }),
  nextTour: (total) => set((s) => ({ tourStep: Math.min(total - 1, s.tourStep + 1) })),
  prevTour: () => set((s) => ({ tourStep: Math.max(0, s.tourStep - 1) })),
}));

window.addEventListener("hashchange", () => useUi.setState({ selection: null, ...fromHash() }));

useUi.subscribe((s) => {
  const id = s.view === "workflow" ? s.workflowId : s.view === "runs" ? s.runId
    : s.view === "artifacts" ? s.artifactId : null;
  const hash = `#/${s.view}${id ? `/${encodeURIComponent(id)}` : ""}`;
  if (window.location.hash !== hash) window.history.pushState(null, "", hash);
});
