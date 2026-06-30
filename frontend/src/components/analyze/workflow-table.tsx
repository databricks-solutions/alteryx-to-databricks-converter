import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import type { WorkflowAnalysis } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConvertBridge } from "@/stores/convert-bridge";
import { motion } from "motion/react";
import { ArrowUpDown, ArrowRightLeft } from "lucide-react";

interface WorkflowTableProps {
  workflows: WorkflowAnalysis[];
}

const priorityVariant: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  High: "success",
  Medium: "warning",
  Low: "destructive",
};

type SortKey = "workflow_name" | "node_count" | "coverage_percentage" | "complexity_score" | "migration_priority";

const priorityOrder: Record<string, number> = { High: 3, Medium: 2, Low: 1 };

export function WorkflowTable({ workflows }: WorkflowTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("coverage_percentage");
  const [sortAsc, setSortAsc] = useState(false);
  const [filter, setFilter] = useState("");
  const setConvertHint = useConvertBridge((s) => s.setWorkflowName);

  const sorted = useMemo(() => {
    let filtered = workflows;
    if (filter) {
      const q = filter.toLowerCase();
      filtered = workflows.filter(
        (w) =>
          w.workflow_name.toLowerCase().includes(q) ||
          w.migration_priority.toLowerCase().includes(q),
      );
    }
    return [...filtered].sort((a, b) => {
      let cmp: number;
      if (sortKey === "migration_priority") {
        cmp = (priorityOrder[a.migration_priority] ?? 0) - (priorityOrder[b.migration_priority] ?? 0);
      } else if (sortKey === "workflow_name") {
        cmp = a.workflow_name.localeCompare(b.workflow_name);
      } else {
        cmp = (a[sortKey] as number) - (b[sortKey] as number);
      }
      return sortAsc ? cmp : -cmp;
    });
  }, [workflows, sortKey, sortAsc, filter]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Filter workflows..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="flex-1 max-w-xs rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] placeholder:text-[var(--fg-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
          aria-label="Filter workflows"
        />
        <span className="text-xs text-[var(--fg-muted)]">
          {sorted.length} of {workflows.length} workflows
        </span>
      </div>

      <div className="rounded-xl border border-[var(--border)] overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--bg-sidebar)] border-b border-[var(--border)]">
              <SortHeader label="Workflow" sortKey="workflow_name" current={sortKey} asc={sortAsc} onSort={toggleSort} align="left" />
              <SortHeader label="Nodes" sortKey="node_count" current={sortKey} asc={sortAsc} onSort={toggleSort} align="right" />
              <SortHeader label="Coverage" sortKey="coverage_percentage" current={sortKey} asc={sortAsc} onSort={toggleSort} align="right" />
              <SortHeader label="Complexity" sortKey="complexity_score" current={sortKey} asc={sortAsc} onSort={toggleSort} align="right" />
              <SortHeader label="Priority" sortKey="migration_priority" current={sortKey} asc={sortAsc} onSort={toggleSort} align="center" />
              <th className="text-center px-4 py-3 font-medium text-[var(--fg-muted)]">Effort</th>
              <th className="text-center px-4 py-3 font-medium text-[var(--fg-muted)]">Action</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((w, i) => (
              <motion.tr
                key={w.workflow_name}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: Math.min(i * 0.02, 0.5) }}
                className="border-b border-[var(--border)] last:border-b-0"
              >
                <td className="px-4 py-3 font-medium text-[var(--fg)]">{w.workflow_name}</td>
                <td className="px-4 py-3 text-right text-[var(--fg-muted)]">{w.node_count}</td>
                <td className="px-4 py-3 text-right text-[var(--fg)]">{w.coverage_percentage.toFixed(1)}%</td>
                <td className="px-4 py-3 text-right text-[var(--fg-muted)]">
                  {w.complexity_score.toFixed(1)} ({w.complexity_level})
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge variant={priorityVariant[w.migration_priority] ?? "secondary"}>
                    {w.migration_priority}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge variant={priorityVariant[w.estimated_effort] ?? "secondary"}>
                    {w.estimated_effort}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-center">
                  <Link to="/convert" onClick={() => setConvertHint(w.workflow_name)}>
                    <Button variant="ghost" size="sm">
                      <ArrowRightLeft className="h-3.5 w-3.5" />
                      Convert
                    </Button>
                  </Link>
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SortHeader({
  label,
  sortKey,
  current,
  asc,
  onSort,
  align,
}: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  asc: boolean;
  onSort: (k: SortKey) => void;
  align: "left" | "right" | "center";
}) {
  const active = current === sortKey;
  const alignClass = { left: "text-left", right: "text-right", center: "text-center" }[align];
  return (
    <th
      className={`px-4 py-3 font-medium text-[var(--fg-muted)] cursor-pointer hover:text-[var(--fg)] select-none ${alignClass}`}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown className={`h-3 w-3 ${active ? "text-[var(--ring)]" : "opacity-30"}`} />
        {active && <span className="text-[10px]">{asc ? "asc" : "desc"}</span>}
      </span>
    </th>
  );
}
