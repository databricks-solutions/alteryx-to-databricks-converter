import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { NextStep } from "@/components/shared/next-step";
import { useEstateStore } from "@/stores/estate";
import { AnalyzePage } from "@/routes/analyze";
import { AssessPage } from "@/routes/assess";
import { PortfolioPage } from "@/routes/portfolio";

/**
 * One "Assess your estate" surface. The three analyses that all take the same
 * Alteryx upload — the per-workflow readiness report, the tool-by-difficulty
 * profile, and the cross-workflow dependency/wave plan — used to be three
 * separate tabs a first-time user couldn't tell apart. They're now views over a
 * single shared estate (see `stores/estate.ts`): upload once on any view, switch
 * freely, and each view's result persists so nothing is recomputed on a switch.
 */
export function AssessHubPage() {
  const [view, setView] = useState("report");
  const results = useEstateStore((s) => s.results);
  const hasResult = Boolean(results.analyze || results.profile || results.portfolio);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Assess Your Estate"
        description="Upload your Alteryx workflows once, then explore migration readiness, tool difficulty, and cross-workflow dependencies — all on the same estate."
      />
      <Tabs value={view} onValueChange={setView}>
        <TabsList>
          <TabsTrigger value="report">Readiness report</TabsTrigger>
          <TabsTrigger value="difficulty">Difficulty tiers</TabsTrigger>
          <TabsTrigger value="portfolio">Dependencies &amp; waves</TabsTrigger>
        </TabsList>
        <TabsContent value="report">
          <AnalyzePage embedded />
        </TabsContent>
        <TabsContent value="difficulty">
          <AssessPage embedded />
        </TabsContent>
        <TabsContent value="portfolio">
          <PortfolioPage embedded />
        </TabsContent>
      </Tabs>

      {hasResult && (
        <NextStep
          prompt="Assessed your estate. Next:"
          links={[
            { to: "/business-case", label: "Build the business case" },
            { to: "/convert", label: "Start converting" },
          ]}
        />
      )}
    </div>
  );
}
