import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { MetricCard } from "@/components/shared/metric-card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useAdvise } from "@/hooks/use-insights";
import { downloadJson } from "@/lib/portfolio-download";
import type { CloudName } from "@/lib/api";
import { Play, Loader2, RotateCcw, Download, Server, Zap, Info } from "lucide-react";

const PRIORITY_VARIANT: Record<string, "destructive" | "warning" | "secondary"> = {
  high: "destructive",
  medium: "warning",
  low: "secondary",
};

export function AdvisePage() {
  const [files, setFiles] = useState<File[]>([]);
  const [cloud, setCloud] = useState<CloudName>("aws");
  const mutation = useAdvise();
  const report = mutation.data;

  const handleAdvise = () => {
    if (files.length === 0) return;
    mutation.mutate({ file: files[0], cloud });
  };

  const handleReset = () => {
    mutation.reset();
    setFiles([]);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Cost & Performance Advisor"
        description="Recommend a starting cluster size and surface Spark optimization opportunities for a workflow"
      >
        {report && (
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => downloadJson(report, `${report.workflow_name}-advisory.json`)}
            >
              <Download className="h-4 w-4" />
              Export JSON
            </Button>
            <Button variant="secondary" size="sm" onClick={handleReset}>
              <RotateCcw className="h-4 w-4" />
              New Advisory
            </Button>
          </>
        )}
      </PageHeader>

      {/* Set expectations: this is a planning aid, not a benchmark. */}
      <div className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 text-xs text-[var(--fg-muted)]">
        <Info className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          Recommendations are derived from the workflow's shape — node count, DAG depth, shuffle and
          spatial/ML operations — not from your data volumes. Treat this as a{" "}
          <strong className="text-[var(--fg)]">starting point for planning</strong>, not a benchmark or a
          cost quote.
        </span>
      </div>

      {!report && (
        <div className="space-y-4">
          <FileDropzone files={files} onFilesChange={setFiles} />
          <div className="flex items-center gap-3">
            <label htmlFor="advise-cloud" className="text-sm text-[var(--fg-muted)]">
              Target cloud
            </label>
            <select
              id="advise-cloud"
              value={cloud}
              onChange={(e) => setCloud(e.target.value as CloudName)}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-1.5 text-sm text-[var(--fg)]"
            >
              <option value="aws">AWS</option>
              <option value="azure">Azure</option>
              <option value="gcp">GCP</option>
            </select>
            <Button onClick={handleAdvise} disabled={files.length === 0 || mutation.isPending}>
              {mutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              Get Advisory
            </Button>
          </div>
          {mutation.isError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {mutation.error.message}
            </div>
          )}
        </div>
      )}

      {report && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard label="NODES" value={report.node_count} />
            <MetricCard label="DAG DEPTH" value={report.max_depth} />
            <MetricCard label="WORKERS" value={report.cluster.workers} />
            <MetricCard
              label="REL. DBU/HR"
              value={report.cluster.relative_dbu_per_hour}
              suffix="x"
            />
          </div>

          {/* Cluster recommendation */}
          <Card className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <Server className="h-4 w-4 text-[var(--ring)]" />
              <h2 className="text-sm font-semibold text-[var(--fg)]">Recommended cluster</h2>
            </div>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <Badge>{report.cluster.tier}</Badge>
              <span className="text-sm text-[var(--fg)]">
                {report.cluster.workers} worker{report.cluster.workers === 1 ? "" : "s"}
              </span>
              <code className="rounded bg-[var(--bg-sidebar)] px-1.5 py-0.5 font-mono text-xs">
                {report.cluster.node_type_id}
              </code>
              {report.cluster.photon_recommended && <Badge variant="success">Photon</Badge>}
            </div>
            {report.cluster.rationale.length > 0 && (
              <ul className="list-disc pl-5 space-y-1 text-xs text-[var(--fg-muted)]">
                {report.cluster.rationale.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </Card>

          {/* Optimization hints */}
          <Card className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <Zap className="h-4 w-4 text-[var(--ring)]" />
              <h2 className="text-sm font-semibold text-[var(--fg)]">
                Optimization hints ({report.hints.length})
              </h2>
            </div>
            {report.hints.length === 0 ? (
              <p className="text-sm text-[var(--fg-muted)]">
                No optimization opportunities detected — this workflow's shape has no obvious
                shuffle, broadcast, or caching wins.
              </p>
            ) : (
              <div className="space-y-3">
                {report.hints.map((h, i) => (
                  <div key={i} className="border-t border-[var(--border)] pt-3 first:border-0 first:pt-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <Badge variant={PRIORITY_VARIANT[h.priority] ?? "secondary"}>{h.priority}</Badge>
                      <span className="text-xs text-[var(--fg-muted)]">
                        node {h.node_id} · {h.tool_type || h.hint_type}
                      </span>
                    </div>
                    <p className="text-sm text-[var(--fg)]">{h.suggestion}</p>
                    {h.code_snippet && (
                      <pre className="mt-1.5 overflow-x-auto rounded-lg bg-[var(--bg-sidebar)] p-2 font-mono text-[11px] text-[var(--fg)]">
                        {h.code_snippet}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
