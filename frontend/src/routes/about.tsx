import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useStats } from "@/hooks/use-tools";

export function AboutPage() {
  const { data: stats } = useStats();

  return (
    <div className="space-y-6">
      <PageHeader
        title="About a2d"
        description="Alteryx-to-Databricks Migration Accelerator"
      />

      <Card className="space-y-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--ring)] text-white font-bold text-lg">
            a2d
          </div>
          <div>
            <h2 className="text-lg font-semibold text-[var(--fg)]">
              Alteryx to Databricks
            </h2>
            {stats && (
              <Badge variant="secondary">v{stats.version}</Badge>
            )}
          </div>
        </div>

        <p className="text-sm text-[var(--fg-muted)]">
          Production-grade migration accelerator that parses Alteryx .yxmd workflow
          files and generates equivalent Databricks code in multiple formats.
        </p>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-[var(--fg)] mb-3">Capabilities</h3>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-[var(--border)]">
              <tr>
                <td className="py-2 pr-4 font-medium text-[var(--fg-muted)]">Output Formats</td>
                <td className="py-2 text-[var(--fg)]">PySpark, Spark Declarative Pipelines, Spark SQL, Lakeflow Designer (every conversion produces all four; the highest-confidence one is flagged as &ldquo;best&rdquo;) &middot; cloud-portable Workflow JSON via <code>--cloud aws|azure|gcp</code></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-[var(--fg-muted)]">Supported Tools</td>
                <td className="py-2 text-[var(--fg)]">{stats?.supported_tools ?? "..."} of {stats?.total_tools ?? "..."}</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-[var(--fg-muted)]">Expression Functions</td>
                <td className="py-2 text-[var(--fg)]">{stats?.expression_functions ?? "..."} translated</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-[var(--fg-muted)]">Architecture</td>
                <td className="py-2 text-[var(--fg)]">Parse XML &rarr; IR (typed DAG) &rarr; Generate Code</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-[var(--fg-muted)]">Batch Mode</td>
                <td className="py-2 text-[var(--fg)]">Convert multiple workflows with error accumulation; each file parses IR once and runs all four generators in parallel</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-[var(--fg-muted)]">Analysis</td>
                <td className="py-2 text-[var(--fg)]">Migration readiness assessment with complexity scoring</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-[var(--fg-muted)]">Deploy Readiness</td>
                <td className="py-2 text-[var(--fg)]">3-tier banner (Ready / Needs review / Cannot deploy) plus categorized warnings &mdash; CLI and UI use the same rules</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-[var(--fg)] mb-3">Conversion Methods</h3>
        <div className="space-y-2 text-sm">
          <div className="flex items-start gap-3">
            <Badge variant="success" className="shrink-0">deterministic</Badge>
            <span className="text-[var(--fg-muted)]">Direct 1:1 mapping with full fidelity</span>
          </div>
          <div className="flex items-start gap-3">
            <Badge variant="default" className="shrink-0">expression-engine</Badge>
            <span className="text-[var(--fg-muted)]">Alteryx expressions translated via tokenizer + parser + AST</span>
          </div>
          <div className="flex items-start gap-3">
            <Badge variant="warning" className="shrink-0">template</Badge>
            <span className="text-[var(--fg-muted)]">Code scaffolding that requires manual review</span>
          </div>
          <div className="flex items-start gap-3">
            <Badge variant="secondary" className="shrink-0">mapping</Badge>
            <span className="text-[var(--fg-muted)]">Configuration-based mapping to Databricks equivalent</span>
          </div>
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-[var(--fg)] mb-3">Limitations</h3>
        <ul className="text-sm text-[var(--fg-muted)] space-y-1 list-disc list-inside">
          <li>Spatial tools require a geospatial library (Apache Sedona, H3, or Databricks Labs Mosaic)</li>
          <li>Predictive tools generate MLlib scaffolding requiring model retraining</li>
          <li>Macro workflows may need manual parameter mapping</li>
          <li>Custom connectors require connection override configuration</li>
        </ul>
      </Card>
    </div>
  );
}
