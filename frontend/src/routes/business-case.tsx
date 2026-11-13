import { useState } from "react";
import { StepHeader } from "@/components/layout/step-header";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useProjectContext } from "@/hooks/use-project-context";
import { useEstateStore } from "@/stores/estate";
import { useCurrentResult } from "@/hooks/use-current-result";
import { downloadJson } from "@/lib/portfolio-download";
import { SavingsPage } from "@/routes/savings";
import { ReadinessPage } from "@/routes/readiness";
import { EmptyProject } from "@/components/shared/empty-project";
import { slugify } from "@/lib/files";
import { Download } from "lucide-react";

/**
 * Step 3. The numbers (savings / payback / ROI) and the organizational
 * readiness check, both for this project. No uploads here.
 */
export function BusinessCasePage() {
  const [view, setView] = useState("savings");
  const ctx = useProjectContext();
  const savings = useCurrentResult("savings");
  // The readiness score depends on answers, not files, so read it directly.
  const readiness = useEstateStore((s) => (ctx.projectId ? s.byProject[ctx.projectId]?.readiness?.data : undefined));
  const slug = slugify(ctx.name);

  const exportButton =
    view === "savings" && savings ? (
      <Button variant="secondary" size="sm" onClick={() => downloadJson(savings, `${slug}_savings.json`)}>
        <Download className="h-4 w-4" />
        Download JSON
      </Button>
    ) : view === "readiness" && readiness ? (
      <Button variant="secondary" size="sm" onClick={() => downloadJson(readiness, `${slug}_readiness.json`)}>
        <Download className="h-4 w-4" />
        Download JSON
      </Button>
    ) : null;

  return (
    <div>
      <StepHeader slug="business-case">{exportButton}</StepHeader>
      {ctx.workflows.length === 0 ? (
        <EmptyProject />
      ) : (
        <Tabs value={view} onValueChange={setView}>
          <TabsList>
            <TabsTrigger value="savings">Savings &amp; ROI</TabsTrigger>
            <TabsTrigger value="readiness">Organizational readiness</TabsTrigger>
          </TabsList>
          {/* Both stay mounted so switching tabs keeps unsaved assumptions and answers. */}
          <TabsContent value="savings" forceMount className="data-[state=inactive]:hidden">
            <SavingsPage />
          </TabsContent>
          <TabsContent value="readiness" forceMount className="data-[state=inactive]:hidden">
            <ReadinessPage />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
