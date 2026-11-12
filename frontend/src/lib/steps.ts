import type { WorkflowStage } from "@/lib/api";

/**
 * The migration, in order. The sidebar renders these as the project's steps;
 * it is the app's only navigation, so pages never link "onward" themselves.
 */
export interface StepDef {
  slug: string;
  label: string;
  /** What the step does, in one line (page subtitle). */
  blurb: string;
  /** The lifecycle stage this step moves workflows to, if it tracks one. */
  stage?: WorkflowStage;
  optional?: boolean;
}

export const STEPS: StepDef[] = [
  {
    slug: "workflows",
    label: "Workflows",
    blurb: "The Alteryx files in this migration. This is the only place you add, replace, or remove them.",
  },
  {
    slug: "assess",
    label: "Assess",
    blurb: "Readiness, tool difficulty, and dependencies for every workflow in the project.",
    stage: "assessed",
  },
  {
    slug: "business-case",
    label: "Business case",
    blurb: "Savings, payback and ROI for this estate, plus an organizational readiness check.",
  },
  {
    slug: "convert",
    label: "Convert",
    blurb: "Generate Databricks code for the project's workflows, one or all at once.",
    stage: "converted",
  },
  {
    slug: "review",
    label: "Review",
    blurb: "Check a converted workflow node by node, size its cluster, and mark it reviewed.",
    stage: "reviewed",
  },
  {
    slug: "ai-completion",
    label: "AI completion",
    blurb: "Optional. Have a model fill in what the converter couldn't, as a separate, marked copy.",
    optional: true,
  },
];

export function stepPath(projectId: string, slug: string): string {
  return `/p/${projectId}/${slug}`;
}

export function stepIndex(slug: string): number {
  return STEPS.findIndex((s) => s.slug === slug);
}
