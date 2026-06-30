import { PageHeader } from "@/components/layout/page-header";
import { ToolGrid } from "@/components/tools/tool-grid";
import { Skeleton } from "@/components/ui/skeleton";
import { useTools } from "@/hooks/use-tools";

export function ToolsPage() {
  const { data, isLoading, error } = useTools();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tool Support Matrix"
        description="All Alteryx tools and their Databricks conversion status"
      />

      {isLoading && (
        <div className="space-y-4">
          <Skeleton className="h-10 w-72 rounded-lg" />
          <div className="grid grid-cols-3 gap-3">
            {Array.from({ length: 9 }).map((_, i) => (
              <Skeleton key={i} className="h-32 rounded-xl" />
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error.message}
        </div>
      )}

      {data && (
        <ToolGrid
          categories={data.categories}
          totalTools={data.total_tools}
          supportedTools={data.supported_tools}
        />
      )}
    </div>
  );
}
