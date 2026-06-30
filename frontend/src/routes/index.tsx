import { motion } from "motion/react";
import { Link } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";
import { MetricCard } from "@/components/shared/metric-card";
import { useStats } from "@/hooks/use-tools";
import { useLocalHistoryStore } from "@/stores/local-history";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ArrowRightLeft,
  BarChart3,
  Boxes,
  Code,
  Database,
  Layers,
  Zap,
  Clock,
  FileCheck,
} from "lucide-react";

const quickActions = [
  {
    icon: BarChart3,
    title: "Analyze",
    description: "Assess migration readiness of your workflows",
    to: "/analyze",
  },
  {
    icon: ArrowRightLeft,
    title: "Convert",
    description: "Generate PySpark, Spark Declarative Pipelines, SQL, and Lakeflow in one shot — best format auto-flagged",
    to: "/convert",
  },
  {
    icon: Layers,
    title: "Batch Convert",
    description: "Convert multiple workflows at once with progress tracking",
    to: "/convert/batch",
  },
  {
    icon: Clock,
    title: "History",
    description: "Browse past conversions",
    to: "/history",
  },
];

export function HomePage() {
  const { data: stats, isLoading, error } = useStats();
  const localItems = useLocalHistoryStore((s) => s.items);
  const recentConversions = localItems.slice(0, 5);

  return (
    <div className="space-y-10">
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[var(--ring)] to-blue-700 p-10 text-white"
      >
        <div className="relative z-10">
          <motion.h1
            className="text-4xl font-bold mb-3"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            Alteryx to Databricks
          </motion.h1>
          <motion.p
            className="text-lg text-white/80 max-w-xl"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
          >
            Enterprise-grade migration accelerator. Analyze, convert, and track
            your workflow migration in one place.
          </motion.p>
          <motion.div
            className="mt-6 flex gap-3"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
          >
            <Link
              to="/analyze"
              className="inline-flex items-center gap-2 rounded-lg bg-white/20 hover:bg-white/30 px-4 py-2 text-sm font-medium transition-colors"
            >
              <BarChart3 className="h-4 w-4" />
              Start with Analysis
            </Link>
            <Link
              to="/convert"
              className="inline-flex items-center gap-2 rounded-lg bg-white text-blue-700 hover:bg-white/90 px-4 py-2 text-sm font-medium transition-colors"
            >
              <ArrowRightLeft className="h-4 w-4" />
              Convert a Workflow
            </Link>
          </motion.div>
        </div>
        <div className="absolute -top-20 -right-20 h-64 w-64 rounded-full bg-white/5" />
        <div className="absolute -bottom-10 -right-10 h-40 w-40 rounded-full bg-white/5" />
      </motion.div>

      {/* Quick actions */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {quickActions.map((f, i) => (
          <motion.div
            key={f.title}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + i * 0.05 }}
          >
            <Link to={f.to}>
              <Card className="group cursor-pointer hover:shadow-md hover:-translate-y-0.5 transition-all duration-200">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--ring)]/10 text-[var(--ring)] mb-4 group-hover:bg-[var(--ring)] group-hover:text-white transition-colors">
                  <f.icon className="h-5 w-5" />
                </div>
                <h3 className="font-semibold text-[var(--fg)] mb-1">{f.title}</h3>
                <p className="text-sm text-[var(--fg-muted)]">{f.description}</p>
              </Card>
            </Link>
          </motion.div>
        ))}
      </div>

      {/* First-visit guidance */}
      {recentConversions.length === 0 && (
        <Card className="border-[var(--ring)]/20 bg-[var(--ring)]/5 p-4">
          <p className="text-sm font-medium text-[var(--fg)]">New here? Start with analysis</p>
          <p className="text-xs text-[var(--fg-muted)] mt-1">
            Upload your .yxmd files on the{" "}
            <Link to="/analyze" className="text-[var(--ring)] hover:underline">Analyze</Link> page
            to see a readiness report, then{" "}
            <Link to="/convert" className="text-[var(--ring)] hover:underline">Convert</Link> to generate code.
          </p>
        </Card>
      )}

      {/* Engine stats */}
      {error ? (
        <div className="rounded-xl border border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/30 px-4 py-3">
          <p className="text-sm text-red-700 dark:text-red-400">
            Failed to connect to the API server. Start it with <code className="mx-1 rounded bg-red-100 dark:bg-red-900/40 px-1.5 py-0.5 text-xs">make serve</code> or <code className="rounded bg-red-100 dark:bg-red-900/40 px-1.5 py-0.5 text-xs">uvicorn server.main:app</code>.
          </p>
        </div>
      ) : isLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : stats ? (
        <div>
          <h2 className="text-sm font-semibold text-[var(--fg-muted)] mb-3">Engine Capabilities</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Tool Coverage"
              value={Math.round(stats.supported_tools / stats.total_tools * 100)}
              suffix="%"
              icon={<Boxes className="h-5 w-5" />}
            />
            <MetricCard
              label="Recognized Tools"
              value={stats.total_tools}
              icon={<Database className="h-5 w-5" />}
            />
            <MetricCard
              label="Expression Functions"
              value={stats.expression_functions}
              icon={<Code className="h-5 w-5" />}
            />
            <MetricCard
              label="Output Formats"
              value={stats.output_formats}
              icon={<Zap className="h-5 w-5" />}
            />
          </div>
        </div>
      ) : null}

      {/* Recent conversions */}
      {recentConversions.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-[var(--fg-muted)]">Recent Conversions</h2>
            <Link to="/history" className="text-xs text-[var(--ring)] hover:underline">
              View all
            </Link>
          </div>
          <div className="rounded-xl border border-[var(--border)] overflow-hidden">
            <table className="w-full text-sm">
              <tbody>
                {recentConversions.map((item) => (
                  <tr key={item.id} className="border-b border-[var(--border)] last:border-b-0">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FileCheck className="h-4 w-4 text-green-500" />
                        <span className="font-medium text-[var(--fg)]">{item.workflow_name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-[var(--fg-muted)]">
                      {item.output_format === "multi" || !item.output_format
                        ? "all formats"
                        : item.output_format}
                    </td>
                    <td className="px-4 py-3 text-right text-[var(--fg-muted)]">
                      {new Date(item.created_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
