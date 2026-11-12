import { useEffect, useState } from "react";
import { StepHeader } from "@/components/layout/step-header";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { WorkflowPicker, defaultWorkflowId } from "@/components/shared/workflow-picker";
import { useProjectContext } from "@/hooks/use-project-context";
import { useToastStore } from "@/stores/toast";
import { isAtOrPast } from "@/stores/local-project";
import type { WorkflowStage } from "@/lib/api";
import { ReviewPage } from "@/routes/review";
import { AdvisePage } from "@/routes/advise";
import { ValidatePage } from "@/routes/validate";
import { STAGE_VARIANT } from "@/routes/workflows";
import { EmptyProject } from "@/routes/assess-hub";
import { CheckCircle2, Rocket } from "lucide-react";

/**
 * Step 5. Pick a workflow from the project, check its code node by node, size
 * its cluster, and mark it reviewed (then deployed, once it's running — the
 * app never deploys anything itself).
 */
export function ReviewHubPage() {
  const ctx = useProjectContext();
  const addToast = useToastStore((s) => s.add);
  const [view, setView] = useState("review");
  const [workflowId, setWorkflowId] = useState<string | null>(() => defaultWorkflowId(ctx.workflows, "reviewed"));
  const [file, setFile] = useState<File | null>(null);
  const workflow = ctx.workflows.find((w) => w.id === workflowId) ?? null;

  // Workflows arrive after the first render for a saved project.
  useEffect(() => {
    if (workflowId == null && ctx.workflows.length > 0) setWorkflowId(defaultWorkflowId(ctx.workflows, "reviewed"));
  }, [workflowId, ctx.workflows]);

  // Load the picked workflow's file from the project.
  const { getFile } = ctx;
  useEffect(() => {
    setFile(null);
    if (!workflowId) return;
    let cancelled = false;
    getFile(workflowId)
      .then((f) => !cancelled && setFile(f))
      .catch((e) => addToast(e instanceof Error ? e.message : "Could not load the workflow", "error"));
    return () => {
      cancelled = true;
    };
    // getFile changes identity when the project refetches; only reload on a new pick.
  }, [workflowId]);

  const mark = async (stage: WorkflowStage) => {
    if (!workflow) return;
    try {
      await ctx.setStage(workflow.id, stage);
      addToast(`${workflow.file_name} marked ${stage}`, "success");
    } catch (e) {
      addToast(e instanceof Error ? e.message : "Could not update the workflow", "error");
    }
  };

  return (
    <div>
      <StepHeader slug="review">
        {workflow && !isAtOrPast(workflow.stage, "reviewed") && (
          <Button size="sm" onClick={() => mark("reviewed")} disabled={!isAtOrPast(workflow.stage, "converted")}>
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

      {ctx.workflows.length === 0 ? (
        <EmptyProject />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <WorkflowPicker workflows={ctx.workflows} value={workflowId} onChange={setWorkflowId} />
            {workflow && <Badge variant={STAGE_VARIANT[workflow.stage]}>{workflow.stage}</Badge>}
            {workflow && !isAtOrPast(workflow.stage, "converted") && (
              <span className="text-xs text-[var(--fg-muted)]">
                Not converted yet — convert it on the Convert step before marking it reviewed.
              </span>
            )}
          </div>
          <Tabs value={view} onValueChange={setView}>
            <TabsList>
              <TabsTrigger value="review">Interactive review</TabsTrigger>
              <TabsTrigger value="advise">Cluster &amp; performance</TabsTrigger>
              <TabsTrigger value="validate">Quick syntax check</TabsTrigger>
            </TabsList>
            <TabsContent value="review">
              <ReviewPage file={file} />
            </TabsContent>
            <TabsContent value="advise">
              <AdvisePage file={file} />
            </TabsContent>
            <TabsContent value="validate">
              <p className="mb-4 text-xs text-[var(--fg-muted)]">
                Paste any snippet (for example, a cell you edited) to check its syntax. This doesn't use the
                workflow picked above.
              </p>
              <ValidatePage embedded />
            </TabsContent>
          </Tabs>
        </div>
      )}
    </div>
  );
}
