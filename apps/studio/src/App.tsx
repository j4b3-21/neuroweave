import { Toasts } from "./components/common";
import { Shell } from "./components/Shell";
import { useUi } from "./state/ui";
import { Tour, WelcomeDialog } from "./tour/Tour";
import { ArtifactsView } from "./views/artifacts/ArtifactsView";
import { NodesView } from "./views/NodesView";
import { ProjectView } from "./views/ProjectView";
import { RunsView } from "./views/runs/RunsView";
import { WorkflowView } from "./views/workflow/WorkflowView";

export function App() {
  const view = useUi((s) => s.view);
  return (
    <>
      <Shell>
        {view === "workflow" && <WorkflowView />}
        {view === "runs" && <RunsView />}
        {view === "artifacts" && <ArtifactsView />}
        {view === "nodes" && <NodesView />}
        {view === "project" && <ProjectView />}
      </Shell>
      <WelcomeDialog />
      <Tour />
      <Toasts />
    </>
  );
}
