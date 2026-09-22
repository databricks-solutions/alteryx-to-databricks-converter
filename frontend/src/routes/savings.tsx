import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useSavings, useSavingsDefaults } from "@/hooks/use-insights";
import { downloadJson } from "@/lib/portfolio-download";
import type { CostAssumptions, SavingsReport } from "@/lib/api";
import { Play, Loader2, RotateCcw, Download, PiggyBank, Info, Clock, TrendingUp } from "lucide-react";

/** Format a money amount with a thousands separator and a currency prefix. */
function money(currency: string, amount: number): string {
  return `${currency} ${Math.round(amount).toLocaleString()}`;
}

function MoneyStat({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad" | "neutral";
  hint?: string;
}) {
  const color =
    tone === "good" ? "text-green-500" : tone === "bad" ? "text-red-500" : "text-[var(--fg)]";
  return (
    <Card className="flex flex-col gap-1">
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--fg-muted)]">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      {hint && <p className="text-[11px] leading-snug text-[var(--fg-muted)]">{hint}</p>}
    </Card>
  );
}

/** A labeled number input bound to a field of the assumptions form. */
function NumberField({
  label,
  value,
  onChange,
  step = 1,
  suffix,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  suffix?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-[var(--fg-muted)]">
        {label}
        {suffix ? ` (${suffix})` : ""}
      </span>
      <input
        type="number"
        min={0}
        step={step}
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) =>
          // Clearing the field yields NaN; coerce to 0 so the displayed value and
          // the value sent to the backend agree (JSON.stringify would turn NaN into
          // null, which the server then silently replaces with its default).
          onChange(Number.isFinite(e.target.valueAsNumber) ? e.target.valueAsNumber : 0)
        }
        className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-1.5 text-sm text-[var(--fg)]"
      />
    </label>
  );
}

export function SavingsPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [form, setForm] = useState<CostAssumptions | null>(null);
  const [autoOverride, setAutoOverride] = useState(false);
  const { data: defaults } = useSavingsDefaults();
  const mutation = useSavings();
  const report = mutation.data;

  // Seed the assumptions form from server defaults once they arrive.
  useEffect(() => {
    if (defaults && form === null) {
      setForm({ ...defaults });
      setAutoOverride(defaults.automation_factor !== null);
    }
  }, [defaults, form]);

  const set = (key: keyof CostAssumptions, v: number | null) =>
    setForm((f) => (f ? { ...f, [key]: v } : f));

  const run = () => {
    if (files.length === 0 || !form) return;
    const config: Record<string, unknown> = { ...form };
    // When the override is off, let the backend derive automation from coverage.
    config.automation_factor = autoOverride ? (form.automation_factor ?? 0) : null;
    mutation.mutate({ files, config });
  };

  const reset = () => {
    mutation.reset();
    setFiles([]);
    if (defaults) {
      setForm({ ...defaults });
      setAutoOverride(defaults.automation_factor !== null);
    }
  };

  const cur = report?.currency ?? form?.currency ?? "USD";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Savings & ROI Estimator"
        description="Build the migration business case — license savings, developer time saved, payback and ROI"
      >
        {report && (
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => downloadJson(report, "savings-estimate.json")}
            >
              <Download className="h-4 w-4" />
              Export JSON
            </Button>
            <Button variant="secondary" size="sm" onClick={reset}>
              <RotateCcw className="h-4 w-4" />
              New Estimate
            </Button>
          </>
        )}
      </PageHeader>

      {/* Set expectations: a planning estimate, not a quote. */}
      <div className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 text-xs text-[var(--fg-muted)]">
        <Info className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          Figures combine facts derived from your workflows (count, effort tier, coverage) with the{" "}
          <strong className="text-[var(--fg)]">editable cost assumptions</strong> below. Money defaults are
          illustrative placeholders — replace them with your real contract and rate numbers. This is a{" "}
          <strong className="text-[var(--fg)]">planning estimate, not a quote</strong>.
        </span>
      </div>

      {!report && (
        <div className="space-y-4">
          <FileDropzone files={files} onFilesChange={setFiles} multiple />

          {form && (
            <Card className="flex flex-col gap-5">
              <div>
                <h2 className="text-sm font-semibold text-[var(--fg)]">Cost assumptions</h2>
                <p className="mt-0.5 text-xs text-[var(--fg-muted)]">
                  Tune these to your organization. Everything recomputes when you run the estimate.
                </p>
              </div>

              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">
                  Alteryx licenses retired (annual)
                </p>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <NumberField label="Designer seats" value={form.designer_seats} onChange={(v) => set("designer_seats", v)} />
                  <NumberField label="Cost / seat / yr" suffix={cur} value={form.designer_cost_per_seat_year} onChange={(v) => set("designer_cost_per_seat_year", v)} step={100} />
                  <NumberField label="Server licenses" value={form.server_licenses} onChange={(v) => set("server_licenses", v)} />
                  <NumberField label="Cost / license / yr" suffix={cur} value={form.server_cost_per_license_year} onChange={(v) => set("server_cost_per_license_year", v)} step={1000} />
                </div>
              </div>

              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">
                  Developer rewrite time
                </p>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <NumberField label="Loaded rate / hr" suffix={cur} value={form.developer_hourly_rate} onChange={(v) => set("developer_hourly_rate", v)} step={5} />
                  <NumberField label="Review hrs / workflow" value={form.review_hours_per_workflow} onChange={(v) => set("review_hours_per_workflow", v)} step={0.5} />
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-[var(--fg-muted)]">Automation factor</span>
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={autoOverride}
                        onChange={(e) => setAutoOverride(e.target.checked)}
                        className="h-4 w-4 accent-[var(--ring)]"
                        title="Override; otherwise derived from estate coverage"
                      />
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        disabled={!autoOverride}
                        value={form.automation_factor ?? 0.7}
                        onChange={(e) => set("automation_factor", e.target.valueAsNumber)}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-1.5 text-sm text-[var(--fg)] disabled:opacity-50"
                      />
                    </div>
                    <span className="text-[10px] text-[var(--fg-muted)]">
                      {autoOverride ? "0–1 fraction" : "derived from coverage"}
                    </span>
                  </label>
                </div>
              </div>

              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">
                  Databricks run cost (offset) & maintenance
                </p>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <NumberField label="DBU price" suffix={cur} value={form.dbu_price} onChange={(v) => set("dbu_price", v)} step={0.05} />
                  <NumberField label="DBUs / run" value={form.dbu_per_workflow_run} onChange={(v) => set("dbu_per_workflow_run", v)} step={0.5} />
                  <NumberField label="Runs / month / wf" value={form.runs_per_month} onChange={(v) => set("runs_per_month", v)} />
                  <NumberField label="Maint. savings / yr" suffix={cur} value={form.annual_maintenance_savings} onChange={(v) => set("annual_maintenance_savings", v)} step={1000} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <NumberField label="Horizon" suffix="years" value={form.analysis_horizon_years} onChange={(v) => set("analysis_horizon_years", v)} />
              </div>
            </Card>
          )}

          <div className="flex items-center gap-3">
            <Button onClick={run} disabled={files.length === 0 || !form || mutation.isPending}>
              {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Estimate savings
            </Button>
            {files.length > 0 && (
              <span className="text-xs text-[var(--fg-muted)]">
                {files.length} file{files.length === 1 ? "" : "s"} selected
              </span>
            )}
          </div>

          {mutation.isError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {mutation.error.message}
            </div>
          )}
        </div>
      )}

      {report && <SavingsResults report={report} cur={cur} />}
    </div>
  );
}

function SavingsResults({ report, cur }: { report: SavingsReport; cur: string }) {
  const h = report.headline;
  const payback =
    h.payback_months === null ? "—" : h.payback_months <= 0 ? "Immediate" : `${h.payback_months.toFixed(1)} mo`;
  const roi = h.roi_pct === null ? "—" : `${Math.round(h.roi_pct).toLocaleString()}%`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-6"
    >
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MoneyStat label="Net annual savings" value={money(cur, h.net_annual_savings)} tone={h.net_annual_savings >= 0 ? "good" : "bad"} hint="Licenses + maintenance − Databricks run cost" />
        <MoneyStat label="Payback" value={payback} hint="Time to recoup the migration investment" />
        <MoneyStat label={`${report.assumptions.analysis_horizon_years}-yr ROI`} value={roi} />
        <MoneyStat label="Dev time saved" value={money(cur, h.dev_time_saved)} tone="good" hint={`${Math.round(h.dev_hours_avoided)} hrs automated`} />
      </div>

      {/* Estate grounding */}
      <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--fg-muted)]">
        <Badge>{report.estate.workflow_count} workflows</Badge>
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3.5 w-3.5" />
          {report.estate.total_manual_hours}h manual-rewrite baseline
        </span>
        <span className="inline-flex items-center gap-1">
          <TrendingUp className="h-3.5 w-3.5" />
          mean coverage {report.estate.mean_coverage_pct}%
        </span>
        <span>· automation {Math.round(h.automation_factor_effective * 100)}%</span>
      </div>

      {/* Breakdown */}
      <Card className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <PiggyBank className="h-4 w-4 text-[var(--ring)]" />
          <h2 className="text-sm font-semibold text-[var(--fg)]">Savings breakdown</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--fg-muted)]">
                <th className="pb-2 font-medium">Line</th>
                <th className="pb-2 text-right font-medium">Amount</th>
                <th className="pb-2 font-medium">When</th>
                <th className="pb-2 font-medium">Effect</th>
              </tr>
            </thead>
            <tbody>
              {report.lines.map((line) => (
                <tr key={line.key} className="border-b border-[var(--border)] last:border-0">
                  <td className="py-2 pr-3 text-[var(--fg)]">{line.label}</td>
                  <td className="py-2 text-right tabular-nums text-[var(--fg)]">{money(cur, line.amount)}</td>
                  <td className="py-2 pr-3 text-[var(--fg-muted)]">{line.kind === "one_time" ? "one-time" : "annual"}</td>
                  <td className="py-2">
                    <Badge
                      variant={
                        line.direction === "saving" ? "success" : line.direction === "cost" ? "destructive" : "warning"
                      }
                    >
                      {line.direction}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="text-[11px] text-[var(--fg-muted)]">{report.disclaimer}</p>
    </motion.div>
  );
}
