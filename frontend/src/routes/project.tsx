import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useProjects,
  useActiveProject,
  useCreateProject,
  useAddWorkflows,
  useAssessProject,
} from "@/hooks/use-project";
import { useProjectStore } from "@/stores/project";
import { useToastStore } from "@/stores/toast";
import { useConvertBridge } from "@/stores/convert-bridge";
import { api, type ProjectWorkflow, type WorkflowStage } from "@/lib/api";
import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { FolderPlus, Loader2, Info, Boxes, BarChart3, ArrowRightLeft, Gauge, CheckCircle2 } from "lucide-react";

const STAGE_VARIANT: Record<WorkflowStage, "secondary" | "warning" | "success"> = {
  uploaded: "secondary",
  assessed: "warning",
  converted: "success",
  reviewed: "success",
  deployed: "success",
};

export function ProjectPage() {
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const projects = useProjects();
  const { data: active } = useActiveProject();
  const create = useCreateProject();
  const assessProject = useAssessProject();
  const setActive = useProjectStore((s) => s.setActiveProject);
  const addToast = useToastStore((s) => s.add);
  const setHandoff = useConvertBridge((s) => s.setHandoff);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Mark a workflow deployed — set manually, since the app never deploys
  // customer pipelines. Refreshes the project so the rail/home reflect it.
  const markDeployed = async (projectId: string, workflowId: string) => {
    try {
      await api.updateWorkflowStage(projectId, workflowId, "deployed");
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    } catch (e) {
      addToast(e instanceof Error ? e.message : "Could not update the workflow", "error");
    }
  };

  // Launch a stored workflow into a single-file screen without a re-upload: fetch
  // its bytes, hand them off (with source ids so Convert can advance its stage),
  // and navigate. The destination prefills from the handoff.
  const launch = async (projectId: string, wf: ProjectWorkflow, to: string) => {
    try {
      const file = await api.getProjectWorkflowFile(projectId, wf.id, wf.file_name);
      setHandoff(file, { projectId, workflowId: wf.id });
      navigate({ to });
    } catch (e) {
      addToast(e instanceof Error ? e.message : "Could not load the workflow", "error");
    }
  };

  // The backend returns 503 when no database is configured. Treat that as the
  // graceful "projects not available here" state, not an error to retry.
  const unavailable = projects.isError && /not available|require a database|503/i.test(projects.error.message);

  const handleCreate = () => {
    if (files.length === 0) return;
    create.mutate(
      { name: name.trim() || "Untitled migration", files },
      { onSuccess: () => { setFiles([]); setName(""); } },
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Migration Project"
        description="Upload your Alteryx estate once. Every screen then works from it — no re-uploading — and each workflow tracks its stage from assessed through converted and reviewed."
      />

      {unavailable && (
        <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm">
          <Info className="h-4 w-4 shrink-0 mt-0.5 text-warning" />
          <div>
            <p className="font-medium text-[var(--fg)]">Projects aren't enabled on this server</p>
            <p className="mt-1 text-[var(--fg-muted)]">
              Saving a migration needs a database backend. Without it the app still works per visit —
              upload on each screen as usual. The deployed app has it configured.
            </p>
          </div>
        </div>
      )}

      {!unavailable && (
        <>
          {/* Active project */}
          {active && (
            <Card className="flex flex-col gap-4">
              <div className="flex items-center gap-2">
                <Boxes className="h-4 w-4 text-[var(--ring)]" />
                <h2 className="text-sm font-semibold text-[var(--fg)]">{active.name}</h2>
                <Badge variant="secondary">active</Badge>
                <div className="ml-auto flex items-center gap-3">
                  {active.rollups?.mean_coverage_pct != null && (
                    <span className="text-xs text-[var(--fg-muted)]">
                      {active.rollups.mean_coverage_pct}% avg coverage
                    </span>
                  )}
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={assessProject.isPending}
                    onClick={() =>
                      assessProject.mutate(
                        { projectId: active.id },
                        {
                          onSuccess: () => addToast("Estate assessed — stages updated", "success"),
                          onError: (e) => addToast(e.message, "error"),
                        },
                      )
                    }
                  >
                    {assessProject.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <BarChart3 className="h-4 w-4" />
                    )}
                    Assess estate
                  </Button>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--fg-muted)]">
                      <th className="pb-2 font-medium">Workflow</th>
                      <th className="pb-2 font-medium">Stage</th>
                      <th className="pb-2 text-right font-medium">Launch</th>
                    </tr>
                  </thead>
                  <tbody>
                    {active.workflows.map((w) => (
                      <tr key={w.id} className="border-b border-[var(--border)] last:border-0">
                        <td className="py-2 pr-3 text-[var(--fg)]">{w.file_name}</td>
                        <td className="py-2"><Badge variant={STAGE_VARIANT[w.stage]}>{w.stage}</Badge></td>
                        <td className="py-2 text-right">
                          <div className="flex justify-end gap-1.5">
                            <Button size="sm" variant="ghost" onClick={() => launch(active.id, w, "/convert")}>
                              <ArrowRightLeft className="h-3.5 w-3.5" />
                              Convert
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => launch(active.id, w, "/advise")}>
                              <Gauge className="h-3.5 w-3.5" />
                              Advise
                            </Button>
                            {w.stage !== "deployed" && (
                              <Button size="sm" variant="ghost" onClick={() => markDeployed(active.id, w.id)}>
                                <CheckCircle2 className="h-3.5 w-3.5" />
                                Deployed
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <AddToProject projectId={active.id} />
            </Card>
          )}

          {/* Create a project */}
          <Card className="flex flex-col gap-4">
            <h2 className="text-sm font-semibold text-[var(--fg)]">
              {active ? "Start another migration" : "Create a migration project"}
            </h2>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Project name (e.g. IRB estate migration)"
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--fg)]"
            />
            <FileDropzone files={files} onFilesChange={setFiles} multiple />
            <div className="flex items-center gap-3">
              <Button onClick={handleCreate} disabled={files.length === 0 || create.isPending}>
                {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderPlus className="h-4 w-4" />}
                Create project
              </Button>
              {create.isError && <span className="text-xs text-destructive">{create.error.message}</span>}
            </div>
          </Card>

          {/* Existing projects */}
          {projects.isLoading && <Skeleton className="h-24" />}
          {projects.data && projects.data.projects.length > 0 && (
            <Card className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold text-[var(--fg)]">Saved projects</h2>
              {projects.data.projects.map((p) => (
                <div key={p.id} className="flex items-center justify-between border-b border-[var(--border)] py-2 last:border-0">
                  <div>
                    <span className="text-sm text-[var(--fg)]">{p.name}</span>
                    <span className="ml-2 text-xs text-[var(--fg-muted)]">
                      {p.rollups?.total_workflows ?? 0} workflow(s)
                    </span>
                  </div>
                  {active?.id === p.id ? (
                    <Badge variant="secondary">active</Badge>
                  ) : (
                    <Button size="sm" variant="secondary" onClick={() => setActive(p.id)}>Open</Button>
                  )}
                </div>
              ))}
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function AddToProject({ projectId }: { projectId: string }) {
  const [files, setFiles] = useState<File[]>([]);
  const add = useAddWorkflows();
  return (
    <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-3">
      <p className="text-xs text-[var(--fg-muted)]">Add more workflows to this project</p>
      <FileDropzone files={files} onFilesChange={setFiles} multiple />
      <div>
        <Button
          size="sm"
          variant="secondary"
          disabled={files.length === 0 || add.isPending}
          onClick={() => add.mutate({ id: projectId, files }, { onSuccess: () => setFiles([]) })}
        >
          {add.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Add workflows
        </Button>
      </div>
    </div>
  );
}
