import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useSettingsStore, type BooleanSettingKey } from "@/stores/settings";
import { CheckCircle, RotateCcw } from "lucide-react";

interface CheckboxOption {
  key: BooleanSettingKey;
  label: string;
  description: string;
  preview: string;
}

const CODE_GEN_OPTIONS: CheckboxOption[] = [
  {
    key: "includeComments",
    label: "Include comments",
    description: "Add explanatory comments and performance hints to generated code",
    preview: "# Step 3: FilterNode — High Value Only\nhigh_value_df = df.filter(F.col(\"Amount\") > 100)",
  },
  {
    key: "includeExpressionAudit",
    label: "Expression audit",
    description: "Include expression-level audit showing original → translated mappings",
    preview: "[Amount] * 0.13   →   F.col(\"Amount\") * F.lit(0.13)",
  },
  {
    key: "includePerformanceHints",
    label: "Performance hints",
    description: "Detect broadcast join, persist, and repartition optimization opportunities",
    preview: "Hint: small lookup table detected — wrap with F.broadcast(...)",
  },
  {
    key: "expandMacros",
    label: "Expand macros",
    description: "Resolve .yxmc macro references and convert them as inline functions",
    preview: "# Inlined from CleanseEmail.yxmc (3 nodes)\ndef cleanse_email(df): ...",
  },
];

const EXTRAS_OPTIONS: CheckboxOption[] = [
  {
    key: "generateDdl",
    label: "Unity Catalog DDL",
    description: "Generate CREATE TABLE / EXTERNAL TABLE DDL for Unity Catalog",
    preview: "CREATE TABLE main.default.regional_summary (\n  SalesRegion STRING, TotalSales DOUBLE\n) USING DELTA;",
  },
  {
    key: "generateDab",
    label: "Asset Bundle (DAB)",
    description: "Generate a Databricks Asset Bundle project (databricks.yml, jobs, environments)",
    preview: "databricks.yml  +  resources/sample_workflow.job.yml",
  },
];

function SettingsCheckbox({ checked, onChange, label, description, preview }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description: string;
  preview: string;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 rounded border-[var(--border)] accent-[var(--ring)]"
      />
      <div className="min-w-0 flex-1">
        <span className="text-sm text-[var(--fg)]">{label}</span>
        <p className="text-xs text-[var(--fg-muted)]">{description}</p>
        <pre className="mt-1.5 whitespace-pre-wrap break-words rounded-md border border-dashed border-[var(--border)] bg-[var(--bg-sidebar)]/50 px-2 py-1 font-mono text-[11px] leading-relaxed text-[var(--fg-muted)]/60">
          {preview}
        </pre>
      </div>
    </label>
  );
}

export function SettingsPage() {
  // Settings page genuinely reads every field; subscribing to the whole store
  // here is acceptable since this route only renders when active.
  const settings = useSettingsStore();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Configure conversion defaults. Settings are persisted in your browser."
      />

      {/* Databricks catalog */}
      <Card>
        <h3 className="text-sm font-semibold text-[var(--fg)] mb-4">
          Unity Catalog
        </h3>
        <p className="text-xs text-[var(--fg-muted)] mb-4">
          Specify the catalog and schema used in generated code.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label
              htmlFor="catalog"
              className="block text-xs font-medium text-[var(--fg-muted)] mb-1"
            >
              Catalog Name
            </label>
            <input
              id="catalog"
              type="text"
              value={settings.catalogName}
              onChange={(e) => settings.setCatalogName(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--fg)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
            />
          </div>
          <div>
            <label
              htmlFor="schema"
              className="block text-xs font-medium text-[var(--fg-muted)] mb-1"
            >
              Schema Name
            </label>
            <input
              id="schema"
              type="text"
              value={settings.schemaName}
              onChange={(e) => settings.setSchemaName(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--fg)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
            />
          </div>
        </div>
      </Card>

      {/* Code generation options */}
      <Card>
        <h3 className="text-sm font-semibold text-[var(--fg)] mb-4">
          Code Generation
        </h3>
        <div className="space-y-3">
          {CODE_GEN_OPTIONS.map((opt) => (
            <SettingsCheckbox
              key={opt.key}
              checked={settings[opt.key]}
              onChange={(v) => settings.setBooleanSetting(opt.key, v)}
              label={opt.label}
              description={opt.description}
              preview={opt.preview}
            />
          ))}
        </div>
      </Card>

      {/* Databricks extras */}
      <Card>
        <h3 className="text-sm font-semibold text-[var(--fg)] mb-4">
          Databricks Extras
        </h3>
        <p className="text-xs text-[var(--fg-muted)] mb-4">
          Generate additional Databricks artifacts alongside the converted code.
        </p>
        <div className="space-y-3">
          {EXTRAS_OPTIONS.map((opt) => (
            <SettingsCheckbox
              key={opt.key}
              checked={settings[opt.key]}
              onChange={(v) => settings.setBooleanSetting(opt.key, v)}
              label={opt.label}
              description={opt.description}
              preview={opt.preview}
            />
          ))}
        </div>
      </Card>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-[var(--fg-muted)]">
          <CheckCircle className="h-4 w-4 text-green-500" />
          All settings are saved automatically to your browser.
        </div>
        <Button variant="secondary" size="sm" onClick={() => settings.resetToDefaults()}>
          <RotateCcw className="h-3.5 w-3.5" />
          Reset to Defaults
        </Button>
      </div>
    </div>
  );
}
