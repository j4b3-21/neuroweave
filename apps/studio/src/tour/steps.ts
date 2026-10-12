import type { View } from "../state/ui";

export interface TourStep {
  id: string;
  title: string;
  body: string;
  /** data-tour attribute value to spotlight; omit for a centred card. */
  target?: string;
  view?: View;
  /** Select this node id when the step opens (tutorial projects). */
  selectNode?: string;
  /** Only shown when the project was created by `nw tutor`. */
  tutorialOnly?: boolean;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "welcome",
    title: "Welcome to NeuroWeave Studio",
    body: "This short tour points at the real controls. You can skip anytime and reopen it from Help → Take the tour.",
  },
  {
    id: "workflows",
    title: "Your workflows",
    body: "Every saved workflow appears here. Click one to open the editor. The Studio and the CLI use the same files.",
    target: "workflows",
    view: "workflow",
  },
  {
    id: "palette",
    title: "Node palette",
    body: "Drag or click a definition to add a node. Definitions come from the Python modules listed in Project settings.",
    target: "palette",
    view: "workflow",
  },
  {
    id: "canvas",
    title: "The graph canvas",
    body: "Nodes and typed connections live here. The graph is the source of truth for what will run.",
    target: "canvas",
    view: "workflow",
  },
  {
    id: "bootstrap",
    title: "A node and its ports",
    body: "Coloured ports show type families. Compatible connections are checked by the kernel when you save or run.",
    target: "node-bootstrap",
    view: "workflow",
    selectNode: "bootstrap",
    tutorialOnly: true,
  },
  {
    id: "inspector",
    title: "Parameters",
    body: "Select a node to edit its parameters. Forms are generated from the function's type annotations. Changes autosave.",
    target: "inspector",
    view: "workflow",
  },
  {
    id: "validate",
    title: "Validate",
    body: "Checks missing inputs, type mismatches and unknown node types before you run.",
    target: "validate",
    view: "workflow",
  },
  {
    id: "run",
    title: "Run controls",
    body: "Set a seed, choose whether to reuse cached results, then Run. Live status appears on each node and in the bottom panel.",
    target: "run",
    view: "workflow",
  },
  {
    id: "bottom",
    title: "Problems, latest run and logs",
    body: "Validation issues, the latest run table and per-node logs share this panel.",
    target: "bottom",
    view: "workflow",
  },
  {
    id: "runs",
    title: "Runs and experiments",
    body: "Every execution is recorded. Open a run for nodes, metrics, outputs and environment, or tick two runs to Compare.",
    target: "nav-runs",
    view: "runs",
  },
  {
    id: "reproduce",
    title: "Reproduce",
    body: "Re-executes the exact snapshot with the same seed and no cache, then checks byte-identical outputs. The environment badge sits beside the verdict.",
    target: "reproduce",
    view: "runs",
  },
  {
    id: "artifacts",
    title: "Artifacts",
    body: "Browse results with previews, verify integrity, and open the lineage graph upstream or downstream.",
    target: "nav-artifacts",
    view: "artifacts",
  },
  {
    id: "settings",
    title: "Project settings",
    body: "Name, node modules and the default seed. Only trust modules you would run as an ordinary Python script — there is no sandbox.",
    target: "nav-project",
    view: "project",
  },
  {
    id: "done",
    title: "You're ready",
    body: "Try changing a parameter and pressing Run, or open Help → Take the tour anytime. For the full guided path from the terminal, run `nw tutor`.",
  },
];

export function stepsFor(tutorial: boolean): TourStep[] {
  return TOUR_STEPS.filter((step) => tutorial || !step.tutorialOnly);
}
