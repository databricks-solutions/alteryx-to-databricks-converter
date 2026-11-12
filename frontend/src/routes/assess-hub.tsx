import { useState } from "react";
import { StepHeader } from "@/components/layout/step-header";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useCurrentResult } from "@/hooks/use-current-result";
import { useProjectContext } from "@/hooks/use-project-context";
import { downloadAnalysisCSV } from "@/lib/csv";
import { downloadJson } from "@/lib/portfolio-download";
import { AnalyzePage } from "@/routes/analyze";
import { AssessPage, downloadBlob, profileToCsv } from "@/routes/assess";
import { PortfolioPage } from "@/routes/portfolio";
import { Download } from "lucide-react";

/**
 * Step 2. Three read-only views of the project's workflows. Nothing to upload:
 * each view runs on the project the first time you open it, and again by
 * itself if the project's files change. Export sits in the header, for
 * whichever view is open.
 */
export function AssessHubPage() {
  const [view, setView] = useState("report");
  const ctx = useProjectContext();
  const report = useCurrentResult("analyze");
  const profile = useCurrentResult("profile");
  const portfolio = useCurrentResult("portfolio");
  const slug = ctx.name.replace(/[^A-Za-z0-9_-]+/g, "_") || "project";

  const exportButton =
    view === "report" && report ? (
      <Button variant="secondary" size="sm" onClick={() => downloadAnalysisCSV(report.workflows)}>
        <Download className="h-4 w-4" />
        Export CSV
      </Button>
    ) : view === "difficulty" && profile ? (
      <>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => downloadBlob(`${slug}_profile.csv`, profileToCsv(profile), "text/csv")}
        >
          <Download className="h-4 w-4" />
          Export CSV
        </Button>
        <Button variant="secondary" size="sm" onClick={() => downloadJson(profile, `${slug}_profile.json`)}>
          <Download className="h-4 w-4" />
          Export JSON
        </Button>
      </>
    ) : view === "portfolio" && portfolio ? (
      <Button variant="secondary" size="sm" onClick={() => downloadJson(portfolio, `${slug}_portfolio.json`)}>
        <Download className="h-4 w-4" />
        Export JSON
      </Button>
    ) : null;

  return (
    <div>
      <StepHeader slug="assess">{exportButton}</StepHeader>
      {ctx.workflows.length === 0 ? (
        <EmptyProject />
      ) : (
        <Tabs value={view} onValueChange={setView}>
          <TabsList>
            <TabsTrigger value="report">Readiness report</TabsTrigger>
            <TabsTrigger value="difficulty">Difficulty tiers</TabsTrigger>
            <TabsTrigger value="portfolio">Dependencies &amp; waves</TabsTrigger>
          </TabsList>
          <TabsContent value="report">
            <AnalyzePage />
          </TabsContent>
          <TabsContent value="difficulty">
            <AssessPage />
          </TabsContent>
          <TabsContent value="portfolio">
            <PortfolioPage />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

export function EmptyProject() {
  return (
    <p className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6 text-sm text-[var(--fg-muted)]">
      This project has no workflows yet. Add its Alteryx files on the Workflows step (step 1 in the sidebar).
    </p>
  );
}
