import type { ToolInfo } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle, XCircle } from "lucide-react";
import { motion } from "motion/react";

const methodColors: Record<string, string> = {
  deterministic: "success",
  "expression-engine": "default",
  template: "warning",
  mapping: "secondary",
};

interface ToolCardProps {
  tool: ToolInfo;
  index: number;
}

export function ToolCard({ tool, index }: ToolCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.02, duration: 0.2 }}
    >
      <Card className="h-full hover:shadow-md transition-shadow">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            {tool.supported ? (
              <CheckCircle className="h-4 w-4 text-success shrink-0" />
            ) : (
              <XCircle className="h-4 w-4 text-destructive shrink-0" />
            )}
            <h3 className="font-semibold text-sm text-[var(--fg)]">{tool.tool_type}</h3>
          </div>
          {tool.conversion_method && (
            <Badge
              variant={
                (methodColors[tool.conversion_method] as "success" | "default" | "warning" | "secondary") ??
                "secondary"
              }
              className="text-[10px] shrink-0"
            >
              {tool.conversion_method}
            </Badge>
          )}
        </div>
        {tool.description && (
          <p className="text-xs text-[var(--fg-muted)] mb-2">{tool.description}</p>
        )}
        {tool.databricks_equivalent && (
          <p className="text-xs font-mono text-[var(--ring)]">
            {tool.databricks_equivalent}
          </p>
        )}
      </Card>
    </motion.div>
  );
}
