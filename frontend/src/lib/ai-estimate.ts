import type { AIStatus } from "@/lib/api";

/** Tools that two or more of the steps use: each gets one shared helper first. */
export function sharedTools(steps: { tool_type: string | null }[]): string[] {
  const counts = new Map<string, number>();
  for (const s of steps) if (s.tool_type) counts.set(s.tool_type, (counts.get(s.tool_type) ?? 0) + 1);
  return [...counts].filter(([, n]) => n >= 2).map(([t]) => t);
}

function seconds(s: number): string {
  if (s < 90) return `${Math.max(5, Math.round(s / 5) * 5)} seconds`;
  return `${Math.round(s / 60)} minutes`;
}

/**
 * Before anything is sent: which model, how many steps, and roughly how long.
 * Steps go out a few at a time, so the time is rounds x the time one step
 * usually takes (median to 90th percentile in the committed eval), plus a round
 * for the shared helpers.
 */
export function whatWillHappen(steps: { tool_type: string | null }[], status: AIStatus): string {
  const n = steps.length;
  const tools = sharedTools(steps);
  const par = Math.max(1, status.parallel);
  const rounds = Math.ceil(n / par) + (tools.length ? Math.ceil(tools.length / par) : 0);
  const low = seconds(rounds * status.step_seconds.median);
  const high = seconds(rounds * status.step_seconds.p90);
  const model = status.model ? ` to ${status.model}` : "";
  const helpers = tools.length
    ? ` First it writes one shared helper for ${tools.join(", ")}, which several steps use, so they call the same code.`
    : "";
  const time = low === high ? `about ${low}` : `about ${low} to ${high}`;
  return `This sends ${n} step${n === 1 ? "" : "s"}${model}, ${par} at a time.${helpers} It usually takes ${time}.`;
}
