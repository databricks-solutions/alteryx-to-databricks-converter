import type { WorkflowStage } from "@/lib/api";

/** The lifecycle, in order (mirrors STAGES in server/services/project.py). */
export const STAGE_ORDER: WorkflowStage[] = ["uploaded", "assessed", "converted", "reviewed", "deployed"];

export function isAtOrPast(stage: WorkflowStage, target: WorkflowStage): boolean {
  return STAGE_ORDER.indexOf(stage) >= STAGE_ORDER.indexOf(target);
}

/** Badge color per stage: grey until converted, blue once converted, green once reviewed. */
export const STAGE_VARIANT: Record<WorkflowStage, "secondary" | "default" | "success"> = {
  uploaded: "secondary",
  assessed: "secondary",
  converted: "default",
  reviewed: "success",
  deployed: "success",
};
