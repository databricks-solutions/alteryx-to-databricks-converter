import { lazy, Suspense } from "react";
import {
  createRouter,
  createRoute,
  createRootRoute,
  redirect,
  RouterProvider,
  Outlet,
} from "@tanstack/react-router";
import { useRouterState } from "@tanstack/react-router";
import { Sidebar } from "@/components/layout/sidebar";
import { PageTransition } from "@/components/layout/page-transition";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { ToastContainer } from "@/components/shared/toast-container";
import { useProjectStore } from "@/stores/project";
import { stepPath } from "@/lib/steps";

/**
 * Retry a dynamic import once before giving up.
 *
 * Route chunks are fetched on navigation, so a brief network blip (or a stale
 * chunk after a redeploy) would otherwise drop the user into the error boundary
 * with no way forward. One retry clears the common transient case; a genuine
 * failure still surfaces.
 */
function lazyWithRetry<T extends { default: React.ComponentType<object> }>(load: () => Promise<T>) {
  return lazy(() =>
    load().catch(() => {
      // A redeployed app serves new chunk hashes; a full reload picks them up.
      return new Promise<T>((resolve, reject) => {
        setTimeout(() => load().then(resolve, reject), 500);
      });
    }),
  );
}

// Lazy-load route components for code splitting.
const HomePage = lazyWithRetry(() => import("@/routes/index").then((m) => ({ default: m.HomePage })));
const ProjectLayout = lazyWithRetry(() => import("@/routes/project-layout").then((m) => ({ default: m.ProjectLayout })));
const WorkflowsPage = lazyWithRetry(() => import("@/routes/workflows").then((m) => ({ default: m.WorkflowsPage })));
const AssessHubPage = lazyWithRetry(() => import("@/routes/assess-hub").then((m) => ({ default: m.AssessHubPage })));
const BusinessCasePage = lazyWithRetry(() => import("@/routes/business-case").then((m) => ({ default: m.BusinessCasePage })));
const ConvertPage = lazyWithRetry(() => import("@/routes/convert").then((m) => ({ default: m.ConvertPage })));
const ReviewHubPage = lazyWithRetry(() => import("@/routes/review-hub").then((m) => ({ default: m.ReviewHubPage })));
const AiCompletionPage = lazyWithRetry(() => import("@/routes/ai-completion").then((m) => ({ default: m.AiCompletionPage })));
const ToolsPage = lazyWithRetry(() => import("@/routes/tools").then((m) => ({ default: m.ToolsPage })));
const SyntaxCheckPage = lazyWithRetry(() => import("@/routes/syntax-check").then((m) => ({ default: m.SyntaxCheckPage })));
const AboutPage = lazyWithRetry(() => import("@/routes/about").then((m) => ({ default: m.AboutPage })));
const SettingsPage = lazyWithRetry(() => import("@/routes/settings").then((m) => ({ default: m.SettingsPage })));

function RouteLoading() {
  return (
    <div className="flex items-center justify-center min-h-[200px]">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--ring)] border-t-transparent" />
    </div>
  );
}

// Root layout: the sidebar is the app's one navigation.
function RootLayout() {
  const routerState = useRouterState();
  const key = routerState.location.pathname;

  return (
    <div className="min-h-screen">
      <Sidebar />
      <main className="lg:pl-60 min-h-screen">
        <div className="max-w-6xl mx-auto px-6 py-8 pt-16 lg:pt-8">
          <ErrorBoundary resetKey={key}>
            <PageTransition routeKey={key}>
              <Suspense fallback={<RouteLoading />}>
                <Outlet />
              </Suspense>
            </PageTransition>
          </ErrorBoundary>
        </div>
      </main>
      <ToastContainer />
    </div>
  );
}

// Route tree
const rootRoute = createRootRoute({ component: RootLayout });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: HomePage });

// Every migration step lives under its project, so the URL says which project
// a screen is showing (and links to a project work).
const projectRoute = createRoute({ getParentRoute: () => rootRoute, path: "/p/$projectId", component: ProjectLayout });
const projectIndexRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/",
  beforeLoad: ({ params }) => {
    throw redirect({ to: stepPath(params.projectId, "workflows") });
  },
});
const step = (path: string, component: ReturnType<typeof lazyWithRetry>) =>
  createRoute({ getParentRoute: () => projectRoute, path, component });
const workflowsRoute = step("workflows", WorkflowsPage);
const assessRoute = step("assess", AssessHubPage);
const businessCaseRoute = step("business-case", BusinessCasePage);
const convertRoute = step("convert", ConvertPage);
const reviewRoute = step("review", ReviewHubPage);
const aiRoute = step("ai-completion", AiCompletionPage);

const toolsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/reference/tools", component: ToolsPage });
const syntaxRoute = createRoute({ getParentRoute: () => rootRoute, path: "/reference/syntax-check", component: SyntaxCheckPage });
const aboutRoute = createRoute({ getParentRoute: () => rootRoute, path: "/about", component: AboutPage });
const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/settings", component: SettingsPage });

// Old URLs (bookmarks, docs, links in messages) from before steps lived under a
// project: send them to that step of the last project opened, or to Projects.
function legacyStep(path: string, slug: string) {
  return createRoute({
    getParentRoute: () => rootRoute,
    path,
    beforeLoad: () => {
      const last = useProjectStore.getState().lastProjectId;
      throw redirect({ to: last ? stepPath(last, slug) : "/" });
    },
  });
}
function legacyRedirect(path: string, to: string) {
  return createRoute({
    getParentRoute: () => rootRoute,
    path,
    beforeLoad: () => {
      throw redirect({ to });
    },
  });
}
const legacyRoutes = [
  legacyStep("/project", "workflows"),
  legacyStep("/assess", "assess"),
  legacyStep("/analyze", "assess"),
  legacyStep("/portfolio", "assess"),
  legacyStep("/business-case", "business-case"),
  legacyStep("/savings", "business-case"),
  legacyStep("/readiness", "business-case"),
  legacyStep("/convert", "convert"),
  legacyStep("/convert/batch", "convert"),
  legacyStep("/history", "convert"),
  legacyStep("/review", "review"),
  legacyRedirect("/validate", "/reference/syntax-check"),
  legacyStep("/advise", "review"),
  legacyStep("/chat", "ai-completion"),
  legacyRedirect("/tools", "/reference/tools"),
];

const routeTree = rootRoute.addChildren([
  indexRoute,
  projectRoute.addChildren([
    projectIndexRoute,
    workflowsRoute,
    assessRoute,
    businessCaseRoute,
    convertRoute,
    reviewRoute,
    aiRoute,
  ]),
  toolsRoute,
  syntaxRoute,
  aboutRoute,
  settingsRoute,
  ...legacyRoutes,
]);

const router = createRouter({ routeTree });

export function App() {
  return (
    <ErrorBoundary>
      <RouterProvider router={router} />
    </ErrorBoundary>
  );
}
