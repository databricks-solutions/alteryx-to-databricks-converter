import { useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { ConversionResults } from "@/components/convert/conversion-results";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useConversion } from "@/hooks/use-conversion";
import { useSettingsStore } from "@/stores/settings";
import { useToastStore } from "@/stores/toast";
import { useLocalHistoryStore } from "@/stores/local-history";
import { useConvertBridge } from "@/stores/convert-bridge";
import { Link } from "@tanstack/react-router";
import { Play, Loader2, RotateCcw, ArrowRight } from "lucide-react";

export function ConvertPage() {
  const [files, setFiles] = useState<File[]>([]);
  const catalogName = useSettingsStore((s) => s.catalogName);
  const schemaName = useSettingsStore((s) => s.schemaName);
  const includeComments = useSettingsStore((s) => s.includeComments);
  const includeExpressionAudit = useSettingsStore((s) => s.includeExpressionAudit);
  const includePerformanceHints = useSettingsStore((s) => s.includePerformanceHints);
  const generateDdl = useSettingsStore((s) => s.generateDdl);
  const generateDab = useSettingsStore((s) => s.generateDab);
  const expandMacros = useSettingsStore((s) => s.expandMacros);
  const addToast = useToastStore((s) => s.add);
  const addToHistory = useLocalHistoryStore((s) => s.add);
  const mutation = useConversion();
  const resultsRef = useRef<HTMLDivElement>(null);
  const bridgeWorkflowName = useConvertBridge((s) => s.workflowName);
  const clearBridge = useConvertBridge((s) => s.clear);

  // Clear bridge hint on unmount. clearBridge is a stable Zustand action,
  // so the dep array won't churn — avoids re-entrant clear() loops.
  useEffect(() => {
    return () => clearBridge();
  }, [clearBridge]);

  const handleConvert = () => {
    if (files.length === 0) return;
    mutation.mutate({
      file: files[0],
      catalogName,
      schemaName,
      includeComments,
      includeExpressionAudit,
      includePerformanceHints,
      generateDdl,
      generateDab,
      expandMacros,
    });
  };

  // On success: toast + scroll + save to local history.
  // addToast and addToHistory are stable Zustand actions.
  useEffect(() => {
    if (mutation.data) {
      addToast(
        `Converted "${mutation.data.workflow_name}" successfully`,
        "success",
      );
      addToHistory(mutation.data);
      setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    }
  }, [mutation.data, addToast, addToHistory]);

  const handleReset = () => {
    mutation.reset();
    setFiles([]);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Convert Workflow"
        description="Upload a single .yxmd file and generate equivalent Databricks code in all supported formats"
      >
        {mutation.data && (
          <Button variant="secondary" size="sm" onClick={handleReset}>
            <RotateCcw className="h-4 w-4" />
            Convert Another
          </Button>
        )}
      </PageHeader>

      {!mutation.data && (
        <>
          {bridgeWorkflowName && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--ring)]/30 bg-[var(--ring)]/5 px-4 py-3 text-sm text-[var(--fg)]">
              <ArrowRight className="h-4 w-4 text-[var(--ring)] shrink-0" />
              Ready to convert <strong>{bridgeWorkflowName}</strong> from your analysis. Upload the .yxmd file below.
            </div>
          )}
          <FileDropzone files={files} onFilesChange={setFiles} />

          <div className="flex items-center gap-3">
            <Button
              onClick={handleConvert}
              disabled={files.length === 0 || mutation.isPending}
            >
              {mutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              Convert
            </Button>
            <div className="flex items-center gap-2 rounded-lg bg-[var(--bg-sidebar)] px-3 py-2 text-xs text-[var(--fg-muted)]">
              <span>
                Using catalog <strong className="text-[var(--fg)]">{catalogName}.{schemaName}</strong>
                {includeComments ? " with comments" : ""}
              </span>
              <Link to="/settings" className="ml-auto text-[var(--ring)] hover:underline whitespace-nowrap">
                Change settings →
              </Link>
            </div>
          </div>
        </>
      )}

      {mutation.isPending && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm text-[var(--fg-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="animate-pulse">
              Generating PySpark, Spark Declarative Pipelines, Spark SQL, and Lakeflow Designer code for {files[0]?.name}
              {files[0] && ` (${(files[0].size / 1024).toFixed(0)} KB)`}...
            </span>
          </div>
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      )}

      {mutation.error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <p className="font-medium mb-1">Conversion failed</p>
          <p>{mutation.error.message}</p>
          <div className="mt-2 text-xs text-destructive/70 space-y-1">
            {mutation.error.message.includes("Failed to fetch") && (
              <p>The API server may be offline. Check that it is running and accessible.</p>
            )}
            {mutation.error.message.includes("422") && (
              <p>The file may not be a valid .yxmd Alteryx workflow. Ensure you are uploading an unmodified .yxmd file.</p>
            )}
            {mutation.error.message.includes("413") && (
              <p>File is too large. Try a smaller workflow file.</p>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="mt-2"
            onClick={handleConvert}
          >
            Retry
          </Button>
        </div>
      )}

      <div ref={resultsRef}>
        {mutation.data && <ConversionResults result={mutation.data} />}
      </div>
    </div>
  );
}
