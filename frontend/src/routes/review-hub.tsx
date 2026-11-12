import { useCallback, useEffect, useState } from "react";
import { StepHeader } from "@/components/layout/step-header";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyProject } from "@/components/shared/empty-project";
import {
  NoConvertedWorkflows,
  WorkflowPicker,
  convertedWorkflows,
  defaultWorkflowId,
} from "@/components/shared/workflow-picker";
import { useProjectContext } from "@/hooks/use-project-context";
import { useToastStore } from "@/stores/toast";
import { isAtOrPast, STAGE_VARIANT } from "@/lib/stages";
import type { WorkflowStage } from "@/lib/api";
import { ReviewPage } from "@/routes/review";
import { AdvisePage } from "@/routes/advise";
import { CheckCircle2, Rocket } from "lucide-react";

/**
 * Step 5. Pick a converted workflow, check its code node by node, size its
 * cluster, and mark it reviewed (then deployed, once it's running; the app never
 * deploys anything itself). Both tabs stay mounted, so switching between them
 * keeps your review decisions and edits.
 */
export function ReviewHubPage() {
  const ctx = useProjectContext();
  const addToast = useToastStore((s) => s.add);
  const [view, setView] = useState("review");
  const [workflowId, setWorkflowId] = useState<string | null>(() => defaultWorkflowId(ctx.workflows, "reviewed"));
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState({ needsReview: 0, resolved: 0, started: false });
  const workflow = ctx.workflows.find((w) => w.id === workflowId) ?? null;
  const onProgress = useCallback((p: typeof progress) => setProgress(p), []);

  // Workflows arrive after the first render for a saved project.
  useEffect(() => {
    if (workflowId == null && ctx.workflows.length > 0) setWorkflowId(defaultWorkflowId(ctx.workflows, "reviewed"));
  }, [workflowId, ctx.workflows]);

  // Load the picked workflow's file from the project (only on a new pick).
  const { getFile } = ctx;
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  useEffect(() => {
    if (!workflowId || loadedFor === workflowId) return;
    let cancelled = false;
    setFile(null);
    getFile(workflowId)
      .then((f) => {
        if (cancelled) return;
        setFile(f);
        setLoadedFor(workflowId);
      })
      .catch((e) => addToast(e instanceof Error ? e.message : "Could not load the workflow", "error"));
    return () => {
      cancelled = true;
    };
  }, [workflowId, loadedFor, getFile, addToast]);

  const mark = async (stage: WorkflowStage) => {
    if (!workflow) return;
    const open = progress.needsReview - progress.resolved;
    if (stage === "reviewed" && progress.started && open > 0) {
      if (!window.confirm(`${open} flagged node${open === 1 ? " is" : "s are"} still open. Mark reviewed anyway?`)) return;
    }
    try {
      await ctx.setStage(workflow.id, stage);
      addToast(`${workflow.file_name} marked ${stage}`, "success");
    } catch (e) {
      addToast(e instanceof Error ? e.message : "Could not update the workflow", "error");
    }
  };

  if (ctx.workflows.length === 0) {
    return (
      <div>
        <StepHeader slug="review" />
        <EmptyProject />
      </div>
    );
  }
  if (convertedWorkflows(ctx.workflows).length === 0) {
    return (
      <div>
        <StepHeader slug="review" />
        <NoConvertedWorkflows what="Review" />
      </div>
    );
  }

  return (
    <div>
      <StepHeader slug="review">
        {workflow && !isAtOrPast(workflow.stage, "reviewed") && (
          <Button size="sm" onClick={() => mark("reviewed")}>
            <CheckCircle2 className="h-4 w-4" />
            Mark reviewed
          </Button>
        )}
        {workflow && isAtOrPast(workflow.stage, "reviewed") && workflow.stage !== "deployed" && (
          <Button size="sm" variant="secondary" onClick={() => mark("deployed")}>
            <Rocket className="h-4 w-4" />
            Mark deployed
          </Button>
        )}
      </StepHeader>

      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <WorkflowPicker workflows={ctx.workflows} value={workflowId} onChange={setWorkflowId} />
          {workflow && <Badge variant={STAGE_VARIANT[workflow.stage]}>{workflow.stage}</Badge>}
        </div>
        <Tabs value={view} onValueChange={setView}>
          <TabsList>
            <TabsTrigger value="review">Interactive review</TabsTrigger>
            <TabsTrigger value="advise">Cluster &amp; performance</TabsTrigger>
          </TabsList>
          <TabsContent value="review" forceMount className="data-[state=inactive]:hidden">
            <ReviewPage key={workflowId ?? ""} file={file} active={view === "review"} onProgress={onProgress} />
          </TabsContent>
          <TabsContent value="advise" forceMount className="data-[state=inactive]:hidden">
            <AdvisePage key={workflowId ?? ""} file={file} active={view === "advise"} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
