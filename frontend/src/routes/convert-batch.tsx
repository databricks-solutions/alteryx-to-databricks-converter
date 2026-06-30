import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { BatchProgress } from "@/components/convert/batch-progress";
import { BatchResults } from "@/components/convert/batch-results";
import { Button } from "@/components/ui/button";
import { useBatchConversion } from "@/hooks/use-batch";
import { useBatchStore } from "@/stores/batch";
import { useSettingsStore } from "@/stores/settings";
import { useToastStore } from "@/stores/toast";
import { api } from "@/lib/api";
import { saveAs } from "file-saver";
import { Play, Loader2, RotateCcw, Download, XCircle, RefreshCcw } from "lucide-react";

export function ConvertBatchPage() {
  const [files, setFiles] = useState<File[]>([]);
  const catalogName = useSettingsStore((s) => s.catalogName);
  const schemaName = useSettingsStore((s) => s.schemaName);
  const includeComments = useSettingsStore((s) => s.includeComments);
  const includeExpressionAudit = useSettingsStore((s) => s.includeExpressionAudit);
  const includePerformanceHints = useSettingsStore((s) => s.includePerformanceHints);
  const generateDdl = useSettingsStore((s) => s.generateDdl);
  const generateDab = useSettingsStore((s) => s.generateDab);
  const expandMacros = useSettingsStore((s) => s.expandMacros);
  const mutation = useBatchConversion();
  const status = useBatchStore((s) => s.status);
  const jobId = useBatchStore((s) => s.jobId);
  const fileResults = useBatchStore((s) => s.fileResults);
  const disconnect = useBatchStore((s) => s.disconnect);
  const reset = useBatchStore((s) => s.reset);
  const addToast = useToastStore((s) => s.add);
  const [downloading, setDownloading] = useState(false);

  const handleCancel = () => {
    disconnect();
    addToast("Batch conversion cancelled", "info");
    reset();
    setFiles([]);
    mutation.reset();
  };

  const failedFiles = fileResults.filter((fr) => !fr.success);
  const convertOpts = {
    catalogName,
    schemaName,
    includeComments,
    includeExpressionAudit,
    includePerformanceHints,
    generateDdl,
    generateDab,
    expandMacros,
  };
  const handleRetryFailed = () => {
    if (failedFiles.length === 0) return;
    const failedNames = new Set(failedFiles.map((fr) => fr.file_name));
    const retryFiles = files.filter((f) => failedNames.has(f.name));
    if (retryFiles.length > 0) {
      reset();
      mutation.reset();
      mutation.mutate({ files: retryFiles, ...convertOpts });
    }
  };

  const handleConvert = () => {
    if (files.length === 0) return;
    mutation.mutate({ files, ...convertOpts });
  };

  const handleReset = () => {
    reset();
    setFiles([]);
    mutation.reset();
  };

  const handleDownload = async () => {
    if (!jobId) return;
    setDownloading(true);
    try {
      const blob = await api.batchDownload(jobId);
      saveAs(blob, `batch-${jobId}.zip`);
      addToast("Batch download started", "success");
    } catch {
      addToast("Download failed", "error");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Batch Convert"
        description="Upload multiple .yxmd files for batch conversion in all supported formats with real-time progress"
      >
        {status === "running" && (
          <Button variant="destructive" size="sm" onClick={handleCancel}>
            <XCircle className="h-4 w-4" />
            Cancel
          </Button>
        )}
        {status === "completed" && (
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={handleDownload}
              disabled={downloading}
            >
              {downloading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              Download All (ZIP)
            </Button>
            {failedFiles.length > 0 && (
              <Button variant="secondary" onClick={handleRetryFailed}>
                <RefreshCcw className="h-4 w-4" />
                Retry Failed ({failedFiles.length})
              </Button>
            )}
            <Button variant="secondary" onClick={handleReset}>
              <RotateCcw className="h-4 w-4" />
              New Batch
            </Button>
          </div>
        )}
      </PageHeader>

      {status === "idle" && (
        <>
          <FileDropzone files={files} onFilesChange={setFiles} multiple />
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
              Convert Batch ({files.length} files)
            </Button>
          </div>
          <p className="text-xs text-[var(--fg-muted)]">
            Catalog: {catalogName}.{schemaName}
            {" | "}
            <Link to="/settings" className="underline hover:text-[var(--fg)]">Change settings</Link>
          </p>
        </>
      )}

      {mutation.error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {mutation.error.message}
        </div>
      )}

      <BatchProgress />
      <BatchResults />
    </div>
  );
}
