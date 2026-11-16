import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type UsageAccess, type UsageEvent, type UsageSummary } from "@/lib/api";

const ACTION_LABEL: Record<string, string> = {
  open_app: "Opened the app",
  convert: "Converted a workflow",
  convert_batch: "Converted workflows",
  analyze: "Assessed workflows",
  assess: "Ran an assessment",
  review: "Reviewed a workflow",
  advise: "Cost advice",
  business_case: "Business case",
  portfolio: "Portfolio",
  readiness: "Readiness score",
  syntax_check: "Syntax check",
  ai_complete: "AI completion",
  ai_suggest: "AI suggestion",
  ai_feedback: "Used/edited/discarded a suggestion",
  project_create: "Created a project",
  workflows_add: "Added workflows",
  workflow_remove: "Removed a workflow",
  project_delete: "Deleted a project",
};

const RANGES = [7, 30, 90, 365];

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

function day(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString() : "—";
}

/** One line about what an event did, from the details the server recorded. */
export function describeEvent(e: UsageEvent): string {
  const d = e.details as Record<string, string | number | undefined>;
  const parts: string[] = [];
  if (d.workflow) parts.push(String(d.workflow));
  else if (typeof d.workflows === "number" && d.workflows > 1) parts.push(`${d.workflows} workflows`);
  if (typeof d.coverage === "number") parts.push(`${d.coverage}% coverage`);
  if (typeof d.completed === "number" && typeof d.steps === "number") parts.push(`${d.completed} of ${d.steps} steps`);
  if (d.result) parts.push(String(d.result));
  return parts.join(" · ");
}

function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <Card className="flex flex-col gap-1">
      <span className="text-xs text-[var(--fg-muted)]">{label}</span>
      <span className="text-2xl font-semibold text-[var(--fg)]">{value}</span>
      {hint && <span className="text-xs text-[var(--fg-muted)]">{hint}</span>}
    </Card>
  );
}

function Why({ access }: { access: UsageAccess }) {
  let text: string;
  if (!access.database) text = "Usage is kept in the app's database, and this deployment doesn't have one.";
  else if (!access.admins_configured)
    text =
      "Nobody can see usage yet: it lists colleagues' emails, so it's only for the people named in A2D_USAGE_ADMINS (comma-separated, in the app's environment).";
  else text = `Only the people in A2D_USAGE_ADMINS can see usage${access.user ? `, and you're signed in as ${access.user}` : ""}.`;
  return (
    <Card>
      <p className="text-sm text-[var(--fg-muted)]">{text}</p>
      {!access.tracking && (
        <p className="mt-2 text-sm text-[var(--fg-muted)]">Tracking is off (A2D_USAGE_TRACKING=false).</p>
      )}
    </Card>
  );
}

function Activity({ data }: { data: UsageSummary }) {
  const t = data.totals;
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="People" value={t.people ?? 0} hint="signed-in users who did something" />
        <Stat label="Workflows converted" value={t.workflows_converted ?? 0} hint="single and batch conversions" />
        <Stat label="AI runs" value={t.ai_runs ?? 0} hint="completions and suggestions" />
        <Stat label="Actions" value={t.events ?? 0} hint={`${t.events_all_time ?? 0} since tracking started`} />
      </div>

      <Card className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-[var(--fg)]">By day (UTC)</h2>
        {data.by_day.length === 0 ? (
          <p className="text-sm text-[var(--fg-muted)]">Nothing in this period yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data.by_day} margin={{ left: 0, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="day" tick={{ fill: "var(--fg-muted)", fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fill: "var(--fg-muted)", fontSize: 11 }} width={32} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="conversions" name="Workflows converted" fill="var(--ring)" radius={[3, 3, 0, 0]} maxBarSize={36} />
              <Bar dataKey="people" name="People" fill="var(--fg-muted)" radius={[3, 3, 0, 0]} maxBarSize={36} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </Card>

      <Card className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-[var(--fg)]">People</h2>
        {data.by_user.length === 0 ? (
          <p className="text-sm text-[var(--fg-muted)]">Nobody yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-[var(--fg-muted)]">
              <tr>
                <th className="py-1 font-medium">Who</th>
                <th className="py-1 font-medium">Conversions</th>
                <th className="py-1 font-medium">AI runs</th>
                <th className="py-1 font-medium">Actions</th>
                <th className="py-1 font-medium">First seen</th>
                <th className="py-1 font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {data.by_user.map((u) => (
                <tr key={u.user} className="border-t border-[var(--border)]">
                  <td className="py-1.5 text-[var(--fg)]">{u.user}</td>
                  <td className="py-1.5">{u.conversions}</td>
                  <td className="py-1.5">{u.ai_runs}</td>
                  <td className="py-1.5">{u.events}</td>
                  <td className="py-1.5 text-[var(--fg-muted)]">{day(u.first_seen)}</td>
                  <td className="py-1.5 text-[var(--fg-muted)]">{when(u.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-[var(--fg)]">Recent activity</h2>
        {data.recent.length === 0 ? (
          <p className="text-sm text-[var(--fg-muted)]">Nothing yet.</p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {data.recent.map((e, i) => (
                <tr key={i} className="border-t border-[var(--border)] first:border-t-0">
                  <td className="py-1.5 pr-3 whitespace-nowrap text-[var(--fg-muted)]">{when(e.at)}</td>
                  <td className="py-1.5 pr-3 text-[var(--fg)]">{e.user ?? "(not signed in)"}</td>
                  <td className="py-1.5 pr-3">{ACTION_LABEL[e.action] ?? e.action}</td>
                  <td className="py-1.5 pr-3 text-[var(--fg-muted)]">{describeEvent(e)}</td>
                  <td className="py-1.5 text-xs text-[var(--fg-muted)]">
                    {e.status != null && e.status >= 400 ? `failed (${e.status})` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

function SavedProjects({ data }: { data: UsageSummary }) {
  const p = data.projects;
  if (!p) return null;
  const stages = Object.entries(p.by_stage)
    .map(([s, n]) => `${n} ${s}`)
    .join(", ");
  return (
    <Card className="flex flex-col gap-1">
      <h2 className="text-sm font-semibold text-[var(--fg)]">Saved projects (all time)</h2>
      <p className="text-sm text-[var(--fg-muted)]">
        {p.projects} project{p.projects === 1 ? "" : "s"} with {p.workflows} workflow{p.workflows === 1 ? "" : "s"}
        {stages ? ` (${stages})` : ""}. First created {day(p.first)}, last changed {day(p.last)}.
      </p>
    </Card>
  );
}

function History({ data }: { data: UsageSummary }) {
  const h = data.history;
  if (!h) return null;
  return (
    <Card className="flex flex-col gap-3">
      <div>
        <h2 className="text-sm font-semibold text-[var(--fg)]">Conversion history from before tracking</h2>
        <p className="mt-1 text-xs text-[var(--fg-muted)]">
          Earlier versions of the app saved every conversion, without who ran it. This is that record, as it was.
        </p>
      </div>
      <p className="text-sm text-[var(--fg-muted)]">
        {h.conversions} conversions of {h.workflows} workflows, {day(h.first)} to {day(h.last)}
        {h.mean_coverage != null ? `, ${h.mean_coverage}% coverage on average` : ""}. By format:{" "}
        {Object.entries(h.by_format)
          .map(([f, n]) => `${f} ${n}`)
          .join(", ")}
        .
      </p>
      {h.by_month.length > 0 && (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={h.by_month} margin={{ left: 0, right: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="month" tick={{ fill: "var(--fg-muted)", fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fill: "var(--fg-muted)", fontSize: 11 }} width={32} />
            <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", fontSize: 12 }} />
            <Bar dataKey="conversions" name="Conversions" fill="var(--ring)" radius={[3, 3, 0, 0]} maxBarSize={36} />
          </BarChart>
        </ResponsiveContainer>
      )}
      <details className="text-sm">
        <summary className="cursor-pointer text-[var(--fg-muted)]">The last {h.recent.length} conversions</summary>
        <table className="mt-2 w-full">
          <tbody>
            {h.recent.map((r, i) => (
              <tr key={i} className="border-t border-[var(--border)]">
                <td className="py-1 pr-3 whitespace-nowrap text-[var(--fg-muted)]">{when(r.at)}</td>
                <td className="py-1 pr-3 text-[var(--fg)]">{r.workflow}</td>
                <td className="py-1 pr-3">{r.format}</td>
                <td className="py-1 text-[var(--fg-muted)]">{r.coverage != null ? `${r.coverage.toFixed(0)}%` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </Card>
  );
}

/** Who used the app, for what, and the conversion history from before tracking. */
export function UsagePage() {
  const [days, setDays] = useState(30);
  const access = useQuery({ queryKey: ["usage-access"], queryFn: api.usageAccess, staleTime: 60_000 });
  const allowed = access.data?.allowed ?? false;
  const data = useQuery({ queryKey: ["usage", days], queryFn: () => api.usage(days), enabled: allowed });

  return (
    <div>
      <PageHeader
        title="Usage"
        description="Who used the app and for what, saved projects, and the conversion history earlier versions kept."
      >
        {allowed && (
          <select
            aria-label="Period"
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-2 py-1 text-sm"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {RANGES.map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
        )}
      </PageHeader>
      <div className="space-y-6">
        {access.isLoading && <Skeleton className="h-32 rounded-xl" />}
        {access.data && !allowed && <Why access={access.data} />}
        {allowed && data.isLoading && <Skeleton className="h-64 rounded-xl" />}
        {data.error && <p className="text-sm text-destructive">{data.error.message}</p>}
        {data.data && (
          <>
            {data.data.since && (
              <p className="text-xs text-[var(--fg-muted)]">Tracking since {when(data.data.since)}.</p>
            )}
            <Activity data={data.data} />
            <SavedProjects data={data.data} />
            <History data={data.data} />
          </>
        )}
      </div>
    </div>
  );
}
