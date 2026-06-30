import { useState, useMemo } from "react";
import type { ToolInfo } from "@/lib/api";
import { CategoryGroup } from "./category-group";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Search } from "lucide-react";

interface ToolGridProps {
  categories: Record<string, ToolInfo[]>;
  totalTools: number;
  supportedTools: number;
}

type Filter = "all" | "supported" | "unsupported";

export function ToolGrid({ categories, totalTools, supportedTools }: ToolGridProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

  const methodLegend = [
    { label: "deterministic", color: "success" as const },
    { label: "expression-engine", color: "default" as const },
    { label: "template", color: "warning" as const },
    { label: "mapping", color: "secondary" as const },
  ];

  const filtered = useMemo(() => {
    const result: Record<string, ToolInfo[]> = {};
    for (const [cat, tools] of Object.entries(categories)) {
      const matching = tools.filter((t) => {
        if (filter === "supported" && !t.supported) return false;
        if (filter === "unsupported" && t.supported) return false;
        if (search) {
          const q = search.toLowerCase();
          return (
            t.tool_type.toLowerCase().includes(q) ||
            (t.description?.toLowerCase().includes(q) ?? false)
          );
        }
        return true;
      });
      if (matching.length > 0) {
        result[cat] = matching;
      }
    }
    return result;
  }, [categories, filter, search]);

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex gap-1 rounded-lg bg-[var(--bg-sidebar)] p-1">
          {(["all", "supported", "unsupported"] as Filter[]).map((f) => (
            <Button
              key={f}
              variant={filter === f ? "default" : "ghost"}
              size="sm"
              onClick={() => setFilter(f)}
              className="capitalize"
            >
              {f}
            </Button>
          ))}
        </div>

        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--fg-muted)]" />
          <input
            type="text"
            aria-label="Search tools"
            placeholder="Search tools..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full h-9 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] pl-9 pr-3 text-sm text-[var(--fg)] placeholder:text-[var(--fg-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
          />
        </div>

        <Badge variant="secondary">
          {supportedTools}/{totalTools} supported ({Math.round(supportedTools / totalTools * 100)}%)
        </Badge>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-2">
        {methodLegend.map((m) => (
          <Badge key={m.label} variant={m.color} className="text-xs">
            {m.label}
          </Badge>
        ))}
      </div>

      {/* Categories */}
      <div className="space-y-8">
        {Object.entries(filtered).map(([cat, tools]) => (
          <CategoryGroup key={cat} category={cat} tools={tools} />
        ))}
      </div>
    </div>
  );
}
