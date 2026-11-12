import { useEffect } from "react";
import { Link, Outlet } from "@tanstack/react-router";
import { Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjectContext } from "@/hooks/use-project-context";
import { useLocalProjectStore } from "@/stores/local-project";
import { useProjectStore } from "@/stores/project";

/**
 * Wraps every step of a project. Makes sure the project in the URL exists
 * before a step renders, and remembers it as the last one opened.
 */
export function ProjectLayout() {
  const ctx = useProjectContext();
  const localName = useLocalProjectStore((s) => s.name);
  const setLast = useProjectStore((s) => s.setLastProject);

  useEffect(() => {
    if (ctx.saved && ctx.projectId && ctx.name) setLast(ctx.projectId);
  }, [ctx.saved, ctx.projectId, ctx.name, setLast]);

  if (ctx.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (ctx.error) {
    return (
      <Message title="This project couldn't be opened">
        {/404|unknown project/i.test(ctx.error.message)
          ? "It may have been deleted. "
          : `The server said: ${ctx.error.message}. `}
        Pick a project from the Projects page.
      </Message>
    );
  }

  if (!ctx.saved && localName == null) {
    return (
      <Message title="This session-only project is gone">
        Projects that aren't saved live in the browser tab, so a reload clears them. Start it again from the
        Projects page.
      </Message>
    );
  }

  return (
    <div className="space-y-6">
      {!ctx.saved && (
        <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 px-4 py-2.5 text-xs text-[var(--fg-muted)]">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <span>
            <strong className="text-[var(--fg)]">Not saved — this browser session only.</strong> This server has no
            database, so the project lives in this tab and a reload clears it. Everything else works the same.
          </span>
        </div>
      )}
      <Outlet />
    </div>
  );
}

function Message({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="mx-auto max-w-xl space-y-2 text-center">
      <h1 className="text-lg font-semibold text-[var(--fg)]">{title}</h1>
      <p className="text-sm text-[var(--fg-muted)]">{children}</p>
      <Link to="/" className="inline-block pt-2 text-sm font-medium text-[var(--ring)] hover:underline">
        Go to Projects
      </Link>
    </Card>
  );
}
