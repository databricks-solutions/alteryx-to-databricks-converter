import type { ToolInfo } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ToolCard } from "./tool-card";

interface CategoryGroupProps {
  category: string;
  tools: ToolInfo[];
}

export function CategoryGroup({ category, tools }: CategoryGroupProps) {
  const supported = tools.filter((t) => t.supported).length;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-lg font-semibold text-[var(--fg)] capitalize">
          {category}
        </h2>
        <Badge variant={supported === tools.length ? "success" : "secondary"}>
          {supported}/{tools.length} ({Math.round(supported / tools.length * 100)}%)
        </Badge>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {tools.map((tool, i) => (
          <ToolCard key={tool.tool_type} tool={tool} index={i} />
        ))}
      </div>
    </div>
  );
}
