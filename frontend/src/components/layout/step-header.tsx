import type { ReactNode } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { useProjectContext } from "@/hooks/use-project-context";
import { STEPS, stepIndex } from "@/lib/steps";

/**
 * The header every migration step uses: which project you're in, which step
 * this is, and what it does — so a screen never leaves you guessing whether
 * (or where) you're inside a project.
 */
export function StepHeader({ slug, children }: { slug: string; children?: ReactNode }) {
  const ctx = useProjectContext();
  const index = stepIndex(slug);
  const def = STEPS[index];
  return (
    <PageHeader
      title={def.label}
      description={def.blurb}
      eyebrow={
        <>
          <span className="text-[var(--fg)]">{ctx.name}</span>
          <span className="mx-1.5">·</span>
          Step {index + 1} of {STEPS.length}
          {def.optional && <span className="ml-1.5">(optional)</span>}
        </>
      }
    >
      {children}
    </PageHeader>
  );
}
