import { useState } from "react";
import { StepHeader } from "@/components/layout/step-header";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useCurrentResult } from "@/hooks/use-current-result";
import { useProjectContext } from "@/hooks/use-project-context";
import { EmptyProject } from "@/components/shared/empty-project";
import { downloadAnalysisCSV, profileToCsv } from "@/lib/csv";
import { downloadText, slugify } from "@/lib/files";
import { downloadJson } from "@/lib/portfolio-download";
import { AnalyzePage } from "@/routes/analyze";
import { AssessPage } from "@/routes/assess";
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
  const slug = slugify(ctx.name);

  const exportButton =
    view === "report" && report ? (
      <Button variant="secondary" size="sm" onClick={() => downloadAnalysisCSV(report.workflows, `${slug}_report.csv`)}>
        <Download className="h-4 w-4" />
        Download CSV
      </Button>
    ) : view === "difficulty" && profile ? (
      <>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => downloadText(`${slug}_difficulty.csv`, profileToCsv(profile), "text/csv;charset=utf-8")}
        >
          <Download className="h-4 w-4" />
          Download CSV
        </Button>
        <Button variant="secondary" size="sm" onClick={() => downloadJson(profile, `${slug}_difficulty.json`)}>
          <Download className="h-4 w-4" />
          Download JSON
        </Button>
      </>
    ) : view === "portfolio" && portfolio ? (
      <Button variant="secondary" size="sm" onClick={() => downloadJson(portfolio, `${slug}_waves.json`)}>
        <Download className="h-4 w-4" />
        Download JSON
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
            <TabsTrigger value="report">Workflow report</TabsTrigger>
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
