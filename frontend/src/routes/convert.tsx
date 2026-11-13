import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import { saveAs } from "file-saver";
import { StepHeader } from "@/components/layout/step-header";
import { ConversionResults } from "@/components/convert/conversion-results";
import { BatchProgress } from "@/components/convert/batch-progress";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { HeaderActions } from "@/components/layout/header-actions";
import { EmptyProject } from "@/components/shared/empty-project";
import { WorkflowName } from "@/components/shared/workflow-name";
import { useProjectContext } from "@/hooks/use-project-context";
import { useConvertOptions } from "@/hooks/use-convert-options";
import { useBatchConversion } from "@/hooks/use-batch";
import { useConversion } from "@/hooks/use-conversion";
import { useBatchStore } from "@/stores/batch";
import { useProjectSettingsStore } from "@/stores/project-settings";
import { useToastStore } from "@/stores/toast";
import { ApiError, type FileResult } from "@/lib/api";
import { api } from "@/lib/api";
import { isAtOrPast, STAGE_VARIANT } from "@/lib/stages";
import { slugify } from "@/lib/files";
import { ArrowLeft, Download, Loader2, Play, RefreshCcw, XCircle, FileCode2 } from "lucide-react";

/**
 * Step 4. Converting one workflow or many is the same action here: pick them
 * and convert. Open any workflow to see its full result (graph, code in every
 * format, deploy readiness).
 */
export function ConvertPage() {
  const ctx = useProjectContext();
  const [openId, setOpenId] = useState<string | null>(null);
  const open = ctx.workflows.find((w) => w.id === openId) ?? null;

  return (
    <div>
      <StepHeader slug="convert" />
      {ctx.workflows.length === 0 ? (
        <EmptyProject />
      ) : open ? (
        <WorkflowResult
          key={open.id}
          workflowId={open.id}
          fileName={open.file_name}
          onBack={() => setOpenId(null)}
        />
      ) : (
        <WorkflowList onOpen={setOpenId} />
      )}
    </div>
  );
}

/** Where this project's generated code reads and writes tables. */
function TargetLocation() {
  const ctx = useProjectContext();
  const opts = useConvertOptions(ctx.projectId);
  const catalogName = opts.catalogName ?? "";
  const schemaName = opts.schemaName ?? "";
  const setLocation = useProjectSettingsStore((s) => s.setLocation);
  const update = (next: { catalogName?: string; schemaName?: string }) => {
    if (ctx.projectId) setLocation(ctx.projectId, { catalogName, schemaName, ...next });
  };
  const input =
    "w-36 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-sm text-[var(--fg)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]";
  return (
    <Card className="flex flex-col gap-2">
      <p className="text-sm font-medium text-[var(--fg)]">Where should this project's code read and write tables?</p>
      <div className="flex flex-wrap items-center gap-1.5 text-sm">
        <input aria-label="Catalog" className={input} value={catalogName} onChange={(e) => update({ catalogName: e.target.value })} />
        <span className="text-[var(--fg-muted)]">.</span>
        <input aria-label="Schema" className={input} value={schemaName} onChange={(e) => update({ schemaName: e.target.value })} />
        <span className="text-xs text-[var(--fg-muted)]">.&lt;table&gt;</span>
      </div>
      <p className="text-xs text-[var(--fg-muted)]">
        The generated notebooks and SQL name tables as <code>catalog.schema.table</code>. Set this to the Unity
        Catalog location this project's migrated tables will live in; it applies to this project only. The default
        for new projects, and the other output options (comments, DDL, asset bundle), are in{" "}
        <Link to="/settings" className="text-[var(--ring)] hover:underline">
          Settings
        </Link>
        .
      </p>
    </Card>
  );
}

function WorkflowList({ onOpen }: { onOpen: (id: string) => void }) {
  const ctx = useProjectContext();
  const opts = useConvertOptions(ctx.projectId);
  const addToast = useToastStore((s) => s.add);
  const batch = useBatchConversion();
  const status = useBatchStore((s) => s.status);
  const jobId = useBatchStore((s) => s.jobId);
  const jobProject = useBatchStore((s) => s.projectId);
  const fileResults = useBatchStore((s) => s.fileResults);
  const errorMessage = useBatchStore((s) => s.errorMessage);
  const resetBatch = useBatchStore((s) => s.reset);
  const disconnect = useBatchStore((s) => s.disconnect);
  const recordedJobId = useBatchStore((s) => s.recordedJobId);
  const markRecorded = useBatchStore((s) => s.markRecorded);
  const mine = jobProject === ctx.projectId;
  const running = mine && status === "running";

  // Default selection: everything not converted yet (or everything, if all are).
  const [selected, setSelected] = useState<Set<string>>(() => {
    const pending = ctx.workflows.filter((w) => !isAtOrPast(w.stage, "converted")).map((w) => w.id);
    return new Set(pending.length > 0 ? pending : ctx.workflows.map((w) => w.id));
  });
  const [downloading, setDownloading] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [starting, setStarting] = useState(false);

  // This job's result per workflow, matched by the name it was sent under.
  const resultByName = useMemo(() => {
    const map = new Map<string, FileResult>();
    if (mine) for (const fr of fileResults) map.set(fr.source_file_name ?? fr.file_name, fr);
    return map;
  }, [mine, fileResults]);

  // When this project's job finishes, record what converted, once per job
  // (the store remembers, so revisiting the step doesn't repeat it).
  const { afterBatch } = ctx;
  useEffect(() => {
    if (!mine || status !== "completed" || !jobId || recordedJobId === jobId) return;
    markRecorded(jobId);
    const converted = fileResults
      .filter((fr) => fr.success)
      .map((fr) => ({
        fileName: fr.source_file_name ?? fr.file_name,
        summary: { coverage: fr.coverage ?? null, best_format: fr.best_format, warnings: fr.warnings.length, at: new Date().toISOString() },
      }));
    afterBatch(converted);
    const failed = fileResults.length - converted.length;
    addToast(
      failed > 0 ? `Converted ${converted.length}, ${failed} failed` : `Converted ${converted.length} workflow(s)`,
      failed > 0 ? "error" : "success",
    );
  }, [mine, status, jobId, recordedJobId, markRecorded, fileResults, afterBatch, addToast]);

  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allSelected = selected.size === ctx.workflows.length;

  const start = async (ids: Set<string>) => {
    if (ids.size === 0 || !ctx.projectId || starting) return;
    const chosen = ctx.workflows.filter((w) => ids.has(w.id));
    setStarting(true);
    resetBatch();
    try {
      if (ctx.saved) {
        await batch.mutateAsync({
          ...opts,
          source: { projectId: ctx.projectId },
          workflowNames: chosen.map((w) => w.file_name),
          projectId: ctx.projectId,
        });
      } else {
        // Session-only project: send the selected files themselves, and the
        // project's macros so the selection can call them.
        const files = await Promise.all(chosen.map((w) => ctx.getFile(w.id)));
        const picked = new Set(chosen.map((w) => w.file_name));
        const macros = ctx.localMacros.filter((m) => !picked.has(m.name));
        await batch.mutateAsync({ ...opts, source: { files, macros }, projectId: ctx.projectId });
      }
    } catch (e) {
      addToast(e instanceof Error ? e.message : "Could not start the conversion", "error");
    } finally {
      setStarting(false);
    }
  };

  const retryFailed = () => {
    const failedNames = new Set(fileResults.filter((fr) => !fr.success).map((fr) => fr.source_file_name ?? fr.file_name));
    start(new Set(ctx.workflows.filter((w) => failedNames.has(w.file_name)).map((w) => w.id)));
  };

  const stop = async () => {
    if (!jobId) return;
    setStopping(true);
    try {
      await api.batchCancel(jobId);
      addToast("Stopped. The workflow in progress will finish; the rest were skipped.", "info");
      disconnect();
      resetBatch();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // The server no longer has this job (it restarted, or the job expired).
        addToast("That run is no longer on the server, so there was nothing to stop.", "info");
        disconnect();
        resetBatch();
      } else {
        addToast(e instanceof Error ? `Could not stop: ${e.message}` : "Could not stop", "error");
      }
    } finally {
      setStopping(false);
    }
  };

  const downloadZip = async () => {
    if (!jobId) return;
    setDownloading(true);
    try {
      saveAs(await api.batchDownload(jobId), `${slugify(ctx.name)}_converted.zip`);
    } catch (e) {
      addToast(
        e instanceof ApiError && e.status === 404
          ? "That run is no longer on the server. Convert again to download."
          : "Download failed",
        "error",
      );
    } finally {
      setDownloading(false);
    }
  };

  const failedCount = mine ? fileResults.filter((fr) => !fr.success).length : 0;

  return (
    <div className="space-y-6">
      <TargetLocation />

      <div className="flex flex-wrap items-center gap-2">
        {running ? (
          <Button variant="destructive" size="sm" onClick={stop} disabled={stopping}>
            <XCircle className="h-4 w-4" />
            {stopping ? "Stopping…" : "Stop"}
          </Button>
        ) : (
          <Button onClick={() => start(selected)} disabled={selected.size === 0 || starting}>
            {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Convert {selected.size === ctx.workflows.length ? "all" : "selected"} ({selected.size})
          </Button>
        )}
        {mine && status === "completed" && (
          <>
            <HeaderActions>
              <Button variant="secondary" size="sm" onClick={downloadZip} disabled={downloading}>
                {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Download ZIP
              </Button>
            </HeaderActions>
            <span className="text-xs text-[var(--fg-muted)]">
              The ZIP has one folder per workflow in this run, with every output format. Workflows that failed
              aren't in it.
            </span>
            {failedCount > 0 && (
              <Button variant="secondary" size="sm" onClick={retryFailed}>
                <RefreshCcw className="h-4 w-4" />
                Retry failed ({failedCount})
              </Button>
            )}
          </>
        )}
      </div>

      {batch.error && <p className="text-sm text-destructive">{batch.error.message}</p>}
      {mine && status === "error" && errorMessage && <p className="text-sm text-destructive">{errorMessage}</p>}
      {mine && <BatchProgress />}

      <Card className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] bg-[var(--bg-sidebar)] text-left text-xs text-[var(--fg-muted)]">
              <th className="w-10 px-4 py-2.5">
                <input
                  type="checkbox"
                  aria-label="Select all"
                  checked={allSelected}
                  onChange={() => setSelected(allSelected ? new Set() : new Set(ctx.workflows.map((w) => w.id)))}
                  className="h-4 w-4 accent-[var(--ring)]"
                />
              </th>
              <th className="px-4 py-2.5 font-medium">Workflow</th>
              <th className="px-4 py-2.5 font-medium">Stage</th>
              <th className="px-4 py-2.5 font-medium">Last conversion</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {ctx.workflows.map((w) => {
              const fr = resultByName.get(w.file_name);
              const coverage = fr?.success ? fr.coverage : w.conversion?.coverage;
              return (
                <tr key={w.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2.5">
                    <input
                      type="checkbox"
                      aria-label={`Select ${w.file_name}`}
                      checked={selected.has(w.id)}
                      onChange={() => toggle(w.id)}
                      className="h-4 w-4 accent-[var(--ring)]"
                    />
                  </td>
                  <td className="px-4 py-2.5 text-[var(--fg)]">
                    <WorkflowName fileName={w.file_name} />
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge variant={STAGE_VARIANT[w.stage]}>{w.stage}</Badge>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-[var(--fg-muted)]">
                    {fr && !fr.success ? (
                      <span className="text-destructive" title={fr.errors?.map((e) => e.message).join("\n")}>
                        Failed{fr.errors?.[0] ? `: ${fr.errors[0].message.slice(0, 80)}` : ""}
                      </span>
                    ) : coverage != null ? (
                      `${Math.round(coverage)}% coverage`
                    ) : (
                      "Not converted yet"
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <Button size="sm" variant="ghost" onClick={() => onOpen(w.id)} aria-label={`Open ${w.file_name}`}>
                      <FileCode2 className="h-3.5 w-3.5" />
                      Open
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/**
 * One workflow's full result: the graph, code in every format, deploy
 * readiness. Opening only looks; it doesn't mark the workflow converted (that
 * happens when you convert it with the button above).
 */
function WorkflowResult({ workflowId, fileName, onBack }: { workflowId: string; fileName: string; onBack: () => void }) {
  const ctx = useProjectContext();
  const opts = useConvertOptions(ctx.projectId);
  const mutation = useConversion();
  const [loadError, setLoadError] = useState<string | null>(null);
  const started = useRef(false);
  const { workflowSource } = ctx;
  const { mutate } = mutation;

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    // A saved project's workflow is read by the server (with the project's
    // macros); a session one is sent with the session's macros.
    const source = workflowSource(workflowId);
    if (source) mutate({ source, ...opts });
    else setLoadError("That workflow is no longer in this project.");
  }, [workflowSource, workflowId, mutate, opts]);

  return (
    <div className="space-y-6">
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-[var(--ring)] hover:underline">
        <ArrowLeft className="h-4 w-4" />
        All workflows
      </button>

      {(mutation.isPending || (!mutation.data && !mutation.error && !loadError)) && (
        <div className="space-y-4" role="status" aria-live="polite">
          <div className="flex items-center gap-2 text-sm text-[var(--fg-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            Generating {fileName} in every output format…
          </div>
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      )}

      {(mutation.error || loadError) && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <p className="font-medium mb-1">Conversion failed</p>
          <p>{loadError ?? mutation.error?.message}</p>
        </div>
      )}

      {mutation.data && <ConversionResults result={mutation.data} />}
    </div>
  );
}
