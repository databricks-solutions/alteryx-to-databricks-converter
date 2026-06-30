import { useState } from "react";
import { useBatchStore } from "@/stores/batch";
import { motion, AnimatePresence } from "motion/react";
import { MetricCard } from "@/components/shared/metric-card";
import { StatusBadge } from "@/components/shared/status-badge";
import { CodeBlock } from "@/components/shared/code-block";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { FORMAT_ORDER, formatLabel } from "@/lib/constants";
import { downloadFormatAsZip } from "@/lib/download";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  FileText,
  ChevronDown,
  Download,
} from "lucide-react";
import { cn } from "@/lib/cn";

export function BatchResults() {
  const status = useBatchStore((s) => s.status);
  const fileResults = useBatchStore((s) => s.fileResults);
  const batchMetrics = useBatchStore((s) => s.batchMetrics);
  const errorsByKind = useBatchStore((s) => s.errorsByKind);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [activeFormatPerRow, setActiveFormatPerRow] = useState<
    Record<string, string>
  >({});

  if (status !== "completed" || !batchMetrics) return null;

  const errorChartData = errorsByKind
    ? Object.entries(errorsByKind).map(([kind, count]) => ({
        kind,
        count,
      }))
    : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Total"
          value={batchMetrics.total_files}
          icon={<FileText className="h-5 w-5" />}
        />
        <MetricCard
          label="Successful"
          value={batchMetrics.successful_files}
          icon={<CheckCircle className="h-5 w-5" />}
        />
        <MetricCard
          label="Partial"
          value={batchMetrics.partial_files}
          icon={<AlertTriangle className="h-5 w-5" />}
        />
        <MetricCard
          label="Failed"
          value={batchMetrics.failed_files}
          icon={<XCircle className="h-5 w-5" />}
        />
      </div>

      {/* Per-file table */}
      <div className="rounded-xl border border-[var(--border)] overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--bg-sidebar)] border-b border-[var(--border)]">
              <th scope="col" className="text-left px-4 py-3 font-medium text-[var(--fg-muted)]">
                Workflow
              </th>
              <th scope="col" className="text-left px-4 py-3 font-medium text-[var(--fg-muted)]">
                Status
              </th>
              <th scope="col" className="text-left px-4 py-3 font-medium text-[var(--fg-muted)]">
                Per-format
              </th>
              <th scope="col" className="text-right px-4 py-3 font-medium text-[var(--fg-muted)]">
                Nodes
              </th>
            </tr>
          </thead>
          <tbody>
            {fileResults.map((fr, i) => {
              const isExpanded = expandedRow === fr.workflow_name;
              const formats = fr.formats ?? {};
              const hasAnyFiles = Object.values(formats).some(
                (f) => f.status === "success" && f.files.length > 0,
              );
              const activeFormat =
                activeFormatPerRow[fr.workflow_name] ||
                fr.best_format ||
                FORMAT_ORDER.find(
                  (f) => formats[f]?.status === "success",
                ) ||
                FORMAT_ORDER[0];
              return (
                <motion.tr
                  key={fr.workflow_name}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: Math.min(i * 0.03, 0.5) }}
                  className={cn(
                    "border-b border-[var(--border)] last:border-b-0 transition-colors",
                    hasAnyFiles && "cursor-pointer hover:bg-[var(--bg-sidebar)]/50",
                  )}
                  onClick={() => hasAnyFiles && setExpandedRow(isExpanded ? null : fr.workflow_name)}
                >
                  <td className="px-4 py-3" colSpan={4}>
                    <div className="grid grid-cols-12 items-center gap-3">
                      <div className="col-span-4 flex items-center gap-2 font-medium text-[var(--fg)]">
                        {hasAnyFiles && (
                          <ChevronDown
                            className={cn(
                              "h-3.5 w-3.5 transition-transform",
                              isExpanded && "rotate-180",
                            )}
                          />
                        )}
                        <span className="truncate">{fr.workflow_name}</span>
                      </div>
                      <div className="col-span-2">
                        <StatusBadge
                          success={fr.success}
                          hasWarnings={fr.warnings.length > 0}
                        />
                      </div>
                      <div className="col-span-5 flex flex-wrap items-center gap-1.5">
                        {FORMAT_ORDER.map((fmt) => {
                          const f = formats[fmt];
                          if (!f) {
                            return (
                              <Badge key={fmt} variant="secondary" className="text-[10px]">
                                {formatLabel(fmt)}: —
                              </Badge>
                            );
                          }
                          const cov =
                            f.status === "success" &&
                            typeof f.stats.coverage_percentage === "number"
                              ? `${(f.stats.coverage_percentage as number).toFixed(0)}%`
                              : "—";
                          return (
                            <Badge
                              key={fmt}
                              variant={
                                f.status === "success" ? "success" : "destructive"
                              }
                              className="text-[10px]"
                              title={f.error || undefined}
                            >
                              {formatLabel(fmt)}: {f.status === "success" ? cov : "fail"}
                            </Badge>
                          );
                        })}
                      </div>
                      <div className="col-span-1 text-right text-[var(--fg-muted)]">
                        {fr.node_count}
                      </div>
                    </div>
                    <AnimatePresence>
                      {isExpanded && hasAnyFiles && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          className="mt-3 space-y-3 overflow-hidden"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {fr.warnings.length > 0 && (
                            <div className="space-y-1">
                              {fr.warnings.map((w, wi) => (
                                <div
                                  key={wi}
                                  className="rounded-lg bg-warning/5 border border-warning/20 px-3 py-2 text-xs text-[var(--fg-muted)]"
                                >
                                  {w}
                                </div>
                              ))}
                            </div>
                          )}
                          <Tabs
                            value={activeFormat}
                            onValueChange={(v) =>
                              setActiveFormatPerRow((prev) => ({
                                ...prev,
                                [fr.workflow_name]: v,
                              }))
                            }
                          >
                            <TabsList>
                              {FORMAT_ORDER.map((fmt) => {
                                const f = formats[fmt];
                                const failed = f?.status === "failed";
                                return (
                                  <TabsTrigger key={fmt} value={fmt}>
                                    <span className="flex items-center gap-1.5">
                                      <span
                                        className={cn(
                                          "inline-block h-2 w-2 rounded-full",
                                          failed
                                            ? "bg-destructive"
                                            : f?.status === "success"
                                              ? "bg-success"
                                              : "bg-[var(--fg-muted)]/40",
                                        )}
                                      />
                                      {formatLabel(fmt)}
                                    </span>
                                  </TabsTrigger>
                                );
                              })}
                            </TabsList>
                            {FORMAT_ORDER.map((fmt) => {
                              const f = formats[fmt];
                              return (
                                <TabsContent key={fmt} value={fmt}>
                                  {!f ? (
                                    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-4 text-xs text-[var(--fg-muted)]">
                                      No result for this format.
                                    </div>
                                  ) : f.status === "failed" ? (
                                    <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-xs">
                                      <div className="flex items-center gap-2 font-medium text-destructive mb-2">
                                        <XCircle className="h-3.5 w-3.5" />
                                        Failed
                                      </div>
                                      {f.error && (
                                        <pre className="whitespace-pre-wrap break-words font-mono text-[11px] text-[var(--fg)]">
                                          {f.error}
                                        </pre>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="space-y-2">
                                      <div className="flex justify-end">
                                        <Button
                                          variant="ghost"
                                          size="sm"
                                          onClick={() =>
                                            downloadFormatAsZip(
                                              f,
                                              fr.workflow_name,
                                            )
                                          }
                                        >
                                          <Download className="h-3.5 w-3.5" />
                                          Download {formatLabel(fmt)}.zip
                                        </Button>
                                      </div>
                                      {f.files.map((file) => (
                                        <CodeBlock
                                          key={file.filename}
                                          code={file.content}
                                          language={file.file_type}
                                          filename={file.filename}
                                        />
                                      ))}
                                    </div>
                                  )}
                                </TabsContent>
                              );
                            })}
                          </Tabs>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </td>
                </motion.tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Error breakdown chart */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6">
        <h3 className="text-sm font-medium text-[var(--fg)] mb-4">
          Errors by Stage
        </h3>
        {errorChartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={errorChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="kind"
                tick={{ fill: "var(--fg-muted)", fontSize: 12 }}
              />
              <YAxis tick={{ fill: "var(--fg-muted)", fontSize: 12 }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  borderRadius: "8px",
                }}
              />
              <Bar dataKey="count" fill="var(--ring)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex items-center justify-center h-[100px] text-sm text-[var(--fg-muted)]">
            <CheckCircle className="h-4 w-4 mr-2 text-green-500" />
            No errors encountered
          </div>
        )}
      </div>
    </motion.div>
  );
}
