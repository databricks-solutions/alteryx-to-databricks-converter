import { useEffect } from "react";
import { Link, Outlet } from "@tanstack/react-router";
import { Info, AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { HeaderActionsProvider } from "@/components/layout/header-actions";
import { useProjectContext } from "@/hooks/use-project-context";
import { ApiError } from "@/lib/api";
import { useProjectStore } from "@/stores/project";

/**
 * Wraps every step of a project. Makes sure the project in the URL exists
 * before a step renders, remembers it as the last one opened, and keeps the
 * project on screen if a background refresh fails.
 */
export function ProjectLayout() {
  const ctx = useProjectContext();
  const setLast = useProjectStore((s) => s.setLastProject);

  useEffect(() => {
    if (ctx.saved && ctx.projectId && ctx.hasData) setLast(ctx.projectId);
  }, [ctx.saved, ctx.projectId, ctx.hasData, setLast]);

  // A session-only project is gone on reload; ask before that happens.
  const guardReload = !ctx.saved && ctx.hasData && ctx.workflows.length > 0;
  useEffect(() => {
    if (!guardReload) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [guardReload]);

  if (ctx.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (ctx.sessionGone) {
    return (
      <Message title="This session-only project is gone">
        Projects that aren't saved live in the browser tab, so a reload or a new session project clears them. Start
        it again from the Projects page.
      </Message>
    );
  }

  if (ctx.error && !ctx.hasData) {
    const notFound = ctx.error instanceof ApiError && ctx.error.status === 404;
    return (
      <Message title={notFound ? "This project doesn't exist" : "This project couldn't be opened"}>
        {notFound ? "It may have been deleted. " : `${ctx.error.message} `}
        {notFound ? "Pick a project from the Projects page." : "Try again in a moment, or go back to Projects."}
      </Message>
    );
  }

  return (
    <HeaderActionsProvider>
      <div className="space-y-6">
        {!ctx.saved && (
          <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 px-4 py-2.5 text-xs text-[var(--fg-muted)]">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span>
              <strong className="text-[var(--fg)]">Not saved — this browser session only.</strong> This server has
              no database, so the project lives in this tab and a reload clears it. Everything else works the same.
            </span>
          </div>
        )}
        {ctx.error && ctx.hasData && (
          <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 px-4 py-2.5 text-xs text-[var(--fg-muted)]">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span>
              Couldn't refresh this project ({ctx.error.message}). What's shown may be a little out of date.{" "}
              <button className="text-[var(--ring)] hover:underline" onClick={ctx.refresh}>
                Try again
              </button>
            </span>
          </div>
        )}
        <Outlet />
      </div>
    </HeaderActionsProvider>
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
