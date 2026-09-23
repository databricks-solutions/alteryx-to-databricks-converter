import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ReviewPage } from "@/routes/review";
import { ValidatePage } from "@/routes/validate";

/**
 * Review + Validate on one surface. Both operate on generated code: the
 * interactive per-node review is the rich path; the paste-a-snippet syntax check
 * is the quick one. Folding the narrow Validate tool in here (rather than a peer
 * top-level tab) keeps "check the code" a single destination.
 */
export function ReviewHubPage() {
  const [view, setView] = useState("review");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Review &amp; Validate"
        description="Inspect and accept the generated code node-by-node, or paste a snippet for a quick syntax check."
      />
      <Tabs value={view} onValueChange={setView}>
        <TabsList>
          <TabsTrigger value="review">Interactive review</TabsTrigger>
          <TabsTrigger value="validate">Quick syntax check</TabsTrigger>
        </TabsList>
        <TabsContent value="review">
          <ReviewPage embedded />
        </TabsContent>
        <TabsContent value="validate">
          <ValidatePage embedded />
        </TabsContent>
      </Tabs>
    </div>
  );
}
