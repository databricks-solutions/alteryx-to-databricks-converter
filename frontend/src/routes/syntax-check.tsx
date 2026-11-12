import { PageHeader } from "@/components/layout/page-header";
import { ValidatePage } from "@/routes/validate";

/** Reference: paste any Python snippet to check its syntax. Not tied to a project. */
export function SyntaxCheckPage() {
  return (
    <div>
      <PageHeader
        eyebrow="Reference"
        title="Syntax check"
        description="Paste any Python snippet (for example, a cell you edited) to check that it parses. This isn't tied to a project."
      />
      <ValidatePage embedded />
    </div>
  );
}
