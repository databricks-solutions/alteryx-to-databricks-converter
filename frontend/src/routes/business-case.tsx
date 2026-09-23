import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { NextStep } from "@/components/shared/next-step";
import { useEstateStore } from "@/stores/estate";
import { SavingsPage } from "@/routes/savings";
import { ReadinessPage } from "@/routes/readiness";

/**
 * The pre-migration "business case" surface for a decision-maker: the numbers
 * (savings / payback / ROI) and the readiness self-assessment, paired because
 * they answer the same two executive questions — "what will this save us?" and
 * "are we ready?" — over the same estate.
 */
export function BusinessCasePage() {
  const [view, setView] = useState("savings");
  const results = useEstateStore((s) => s.results);
  const hasResult = Boolean(results.savings || results.readiness);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Business Case"
        description="Make the case for the migration: estimate savings, payback, and ROI, and score your organizational readiness — both on the estate you've loaded."
      />
      <Tabs value={view} onValueChange={setView}>
        <TabsList>
          <TabsTrigger value="savings">Savings &amp; ROI</TabsTrigger>
          <TabsTrigger value="readiness">Readiness</TabsTrigger>
        </TabsList>
        <TabsContent value="savings">
          <SavingsPage embedded />
        </TabsContent>
        <TabsContent value="readiness">
          <ReadinessPage embedded />
        </TabsContent>
      </Tabs>

      {hasResult && (
        <NextStep
          prompt="Made the business case. Next:"
          links={[{ to: "/convert", label: "Start converting" }]}
        />
      )}
    </div>
  );
}
