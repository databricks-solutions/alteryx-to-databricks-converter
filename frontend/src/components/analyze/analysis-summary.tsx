import { Card } from "@/components/ui/card";
import { Sparkles } from "lucide-react";
import type { AnalysisResult } from "@/lib/api";

interface AnalysisSummaryProps {
  data: AnalysisResult;
}

function complexityLabel(score: number): string {
  if (score < 3) return "low";
  if (score < 6) return "moderate";
  return "high";
}

function plural(n: number, singular: string, pluralForm?: string): string {
  return n === 1 ? singular : (pluralForm ?? singular + "s");
}

function listJoin(parts: string[]): string {
  if (parts.length === 0) return "";
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return `${parts[0]} and ${parts[1]}`;
  return `${parts.slice(0, -1).join(", ")}, and ${parts[parts.length - 1]}`;
}

function buildSummary(data: AnalysisResult): string[] {
  const sentences: string[] = [];

  // 1. Lead
  sentences.push(
    `You uploaded ${data.total_workflows} ${plural(data.total_workflows, "workflow")} ` +
      `containing ${data.total_nodes} ${plural(data.total_nodes, "node", "nodes")} ` +
      `(individual Alteryx tools).`,
  );

  // 2. Convertibility
  const cov = data.avg_coverage;
  const unsupCount = data.unsupported_tools.length;
  if (unsupCount === 0) {
    sentences.push(
      `Every tool you used is supported by the converter — ${cov.toFixed(0)}% can be migrated automatically.`,
    );
  } else {
    const shown = data.unsupported_tools.slice(0, 3);
    const more = unsupCount > 3 ? ` and ${unsupCount - 3} other type${unsupCount - 3 === 1 ? "" : "s"}` : "";
    sentences.push(
      `${cov.toFixed(0)}% can be migrated automatically. ${unsupCount} tool ${plural(
        unsupCount,
        "type",
      )} (${listJoin(shown)}${more}) will need manual work.`,
    );
  }

  // 3. Complexity
  sentences.push(
    `Workflow complexity averages ${data.avg_complexity.toFixed(1)} out of 10 — that's ${complexityLabel(
      data.avg_complexity,
    )}.`,
  );

  // 4. Effort breakdown
  const effortCounts: Record<string, number> = {};
  for (const w of data.workflows) {
    effortCounts[w.estimated_effort] = (effortCounts[w.estimated_effort] ?? 0) + 1;
  }
  const order = ["Low", "Medium", "High", "Very High"];
  const effortParts = order
    .filter((e) => effortCounts[e])
    .map((e) => `${effortCounts[e]} ${e.toLowerCase()}`);
  if (effortParts.length > 0) {
    sentences.push(`Estimated effort: ${listJoin(effortParts)}.`);
  }

  // 5. Top tools
  const top = Object.entries(data.tool_frequency)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)
    .map(([t, n]) => `${t} (${n})`);
  if (top.length > 0) {
    sentences.push(`Most-used tools: ${listJoin(top)}.`);
  }

  // 6. Suggested next step
  const high = data.workflows.filter((w) => w.migration_priority === "High").length;
  if (high > 0) {
    sentences.push(
      `Suggested next step: start with the ${high} high-priority ${plural(high, "workflow")} below.`,
    );
  } else {
    sentences.push(
      `Suggested next step: pick a workflow from the table below and click Convert to generate Databricks code.`,
    );
  }

  return sentences;
}

export function AnalysisSummary({ data }: AnalysisSummaryProps) {
  const sentences = buildSummary(data);
  return (
    <Card className="border-[var(--ring)]/20 bg-[var(--ring)]/5">
      <div className="flex items-start gap-3">
        <Sparkles className="h-5 w-5 shrink-0 text-[var(--ring)]" />
        <div>
          <p className="text-sm font-semibold text-[var(--fg)] mb-1.5">Quick read</p>
          <ul className="space-y-1 text-sm text-[var(--fg-muted)]">
            {sentences.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}
