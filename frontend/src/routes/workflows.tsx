import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { StepHeader } from "@/components/layout/step-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useProjectContext } from "@/hooks/use-project-context";
import { useAddWorkflows, useDeleteProject, useRemoveWorkflow, useRenameProject } from "@/hooks/use-project";
import { useLocalProjectStore } from "@/stores/local-project";
import { useEstateStore } from "@/stores/estate";
import { useProjectStore } from "@/stores/project";
import { useToastStore } from "@/stores/toast";
import type { WorkflowStage } from "@/lib/api";
import { FilePlus2, Loader2, Pencil, Trash2, X, Check } from "lucide-react";

export const STAGE_VARIANT: Record<WorkflowStage, "secondary" | "warning" | "success" | "default"> = {
  uploaded: "secondary",
  assessed: "warning",
  converted: "default",
  reviewed: "success",
  deployed: "success",
};

function formatSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function WorkflowsPage() {
  const ctx = useProjectContext();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.add);
  const local = useLocalProjectStore();
  const forgetResults = useEstateStore((s) => s.forgetProject);
  const lastProjectId = useProjectStore((s) => s.lastProjectId);
  const setLast = useProjectStore((s) => s.setLastProject);
  const addSaved = useAddWorkflows();
  const removeSaved = useRemoveWorkflow();
  const renameSaved = useRenameProject();
  const deleteSaved = useDeleteProject();

  const [adding, setAdding] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState("");

  const empty = ctx.workflows.length === 0;
  const showDropzone = adding || empty;

  const handleAdd = () => {
    if (files.length === 0 || !ctx.projectId) return;
    const replaced = files.filter((f) => ctx.workflows.some((w) => w.file_name === f.name)).length;
    const done = () => {
      setFiles([]);
      setAdding(false);
      addToast(
        replaced > 0
          ? `Added ${files.length - replaced}, replaced ${replaced} with the new version`
          : `Added ${files.length} workflow${files.length === 1 ? "" : "s"}`,
        "success",
      );
    };
    if (!ctx.saved) {
      local.add(files);
      done();
      return;
    }
    addSaved.mutate(
      { id: ctx.projectId, files },
      { onSuccess: done, onError: (e) => addToast(e.message, "error") },
    );
  };

  const handleRemove = (workflowId: string, fileName: string) => {
    if (!window.confirm(`Remove ${fileName} from this project?`)) return;
    if (!ctx.saved) {
      local.remove(workflowId);
      return;
    }
    removeSaved.mutate(
      { projectId: ctx.projectId!, workflowId },
      { onError: (e) => addToast(e.message, "error") },
    );
  };

  const saveName = () => {
    const next = draftName.trim();
    setRenaming(false);
    if (!next || next === ctx.name) return;
    if (!ctx.saved) {
      local.rename(next);
      return;
    }
    renameSaved.mutate({ id: ctx.projectId!, name: next }, { onError: (e) => addToast(e.message, "error") });
  };

  const handleDelete = () => {
    if (!window.confirm(`Delete the project "${ctx.name}" and its stored files? This can't be undone.`)) return;
    const id = ctx.projectId!;
    const finish = () => {
      forgetResults(id);
      if (lastProjectId === id) setLast(null);
      navigate({ to: "/" });
    };
    if (!ctx.saved) {
      local.clear();
      finish();
      return;
    }
    deleteSaved.mutate({ id }, { onSuccess: finish, onError: (e) => addToast(e.message, "error") });
  };

  return (
    <div>
      <StepHeader slug="workflows">
        {!showDropzone && (
          <Button size="sm" onClick={() => setAdding(true)}>
            <FilePlus2 className="h-4 w-4" />
            Add workflows
          </Button>
        )}
      </StepHeader>

      <div className="space-y-6">
        {/* Project name */}
        <div className="flex items-center gap-2 text-sm">
          <span className="text-[var(--fg-muted)]">Project name:</span>
          {renaming ? (
            <>
              <input
                autoFocus
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveName();
                  if (e.key === "Escape") setRenaming(false);
                }}
                className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-2 py-1 text-sm text-[var(--fg)]"
              />
              <Button size="sm" variant="ghost" onClick={saveName} aria-label="Save name">
                <Check className="h-4 w-4" />
              </Button>
            </>
          ) : (
            <>
              <span className="font-medium text-[var(--fg)]">{ctx.name}</span>
              <Button
                size="sm"
                variant="ghost"
                aria-label="Rename project"
                onClick={() => {
                  setDraftName(ctx.name);
                  setRenaming(true);
                }}
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
        </div>

        {/* The one upload in the app (besides creating a project). */}
        {showDropzone && (
          <Card className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <FilePlus2 className="h-4 w-4 text-[var(--ring)]" />
              <h2 className="text-sm font-semibold text-[var(--fg)]">
                {empty ? "Add this project's Alteryx files" : "Add workflows"}
              </h2>
              {!empty && (
                <button
                  aria-label="Cancel"
                  onClick={() => {
                    setAdding(false);
                    setFiles([]);
                  }}
                  className="ml-auto rounded p-1 text-[var(--fg-muted)] hover:text-[var(--fg)]"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
            <p className="text-xs text-[var(--fg-muted)]">
              A file with the same name as one already here replaces it (and starts it over at "uploaded").
            </p>
            <FileDropzone files={files} onFilesChange={setFiles} multiple />
            <div>
              <Button size="sm" onClick={handleAdd} disabled={files.length === 0 || addSaved.isPending}>
                {addSaved.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FilePlus2 className="h-4 w-4" />}
                Add to project
              </Button>
            </div>
          </Card>
        )}

        {/* Workflows */}
        {!empty && (
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--bg-sidebar)] text-left text-xs text-[var(--fg-muted)]">
                  <th className="px-4 py-2.5 font-medium">Workflow</th>
                  <th className="px-4 py-2.5 font-medium">Stage</th>
                  <th className="px-4 py-2.5 text-right font-medium">Coverage</th>
                  <th className="px-4 py-2.5 text-right font-medium">Size</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {ctx.workflows.map((w) => (
                  <tr key={w.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-2.5 text-[var(--fg)]">{w.file_name}</td>
                    <td className="px-4 py-2.5">
                      <Badge variant={STAGE_VARIANT[w.stage]}>{w.stage}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-[var(--fg-muted)]">
                      {w.conversion?.coverage != null
                        ? `${Math.round(w.conversion.coverage)}%`
                        : w.analysis?.coverage_percentage != null
                          ? `${Math.round(w.analysis.coverage_percentage)}%`
                          : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-[var(--fg-muted)]">
                      {formatSize(w.size_bytes)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Remove ${w.file_name}`}
                        onClick={() => handleRemove(w.id, w.file_name)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        <div className="flex justify-end">
          <Button size="sm" variant="ghost" className="text-destructive" onClick={handleDelete}>
            <Trash2 className="h-3.5 w-3.5" />
            Delete project
          </Button>
        </div>
      </div>
    </div>
  );
}
