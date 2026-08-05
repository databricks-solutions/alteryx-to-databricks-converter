import { lazy, Suspense } from "react";
import {
  createRouter,
  createRoute,
  createRootRoute,
  RouterProvider,
  Outlet,
} from "@tanstack/react-router";
import { useRouterState } from "@tanstack/react-router";
import { Sidebar } from "@/components/layout/sidebar";
import { PageTransition } from "@/components/layout/page-transition";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { ToastContainer } from "@/components/shared/toast-container";

/**
 * Retry a dynamic import once before giving up.
 *
 * Route chunks are fetched on navigation, so a brief network blip (or a stale
 * chunk after a redeploy) would otherwise drop the user into the error boundary
 * with no way forward. One retry clears the common transient case; a genuine
 * failure still surfaces.
 */
function lazyWithRetry<T extends { default: React.ComponentType<unknown> }>(
  load: () => Promise<T>,
) {
  return lazy(() =>
    load().catch(() => {
      // A redeployed app serves new chunk hashes; a full reload picks them up.
      return new Promise<T>((resolve, reject) => {
        setTimeout(() => load().then(resolve, reject), 500);
      });
    }),
  );
}

// Lazy-load route components for code splitting
const HomePage = lazyWithRetry(() => import("@/routes/index").then((m) => ({ default: m.HomePage })));
const ConvertPage = lazyWithRetry(() => import("@/routes/convert").then((m) => ({ default: m.ConvertPage })));
const ConvertBatchPage = lazyWithRetry(() => import("@/routes/convert-batch").then((m) => ({ default: m.ConvertBatchPage })));
const AnalyzePage = lazyWithRetry(() => import("@/routes/analyze").then((m) => ({ default: m.AnalyzePage })));
const ToolsPage = lazyWithRetry(() => import("@/routes/tools").then((m) => ({ default: m.ToolsPage })));
const AboutPage = lazyWithRetry(() => import("@/routes/about").then((m) => ({ default: m.AboutPage })));
const HistoryPage = lazyWithRetry(() => import("@/routes/history").then((m) => ({ default: m.HistoryPage })));
const ValidatePage = lazyWithRetry(() => import("@/routes/validate").then((m) => ({ default: m.ValidatePage })));
const ReviewPage = lazyWithRetry(() => import("@/routes/review").then((m) => ({ default: m.ReviewPage })));
const ChatPage = lazyWithRetry(() => import("@/routes/chat").then((m) => ({ default: m.ChatPage })));
const PortfolioPage = lazyWithRetry(() => import("@/routes/portfolio").then((m) => ({ default: m.PortfolioPage })));
const AdvisePage = lazyWithRetry(() => import("@/routes/advise").then((m) => ({ default: m.AdvisePage })));
const SettingsPage = lazyWithRetry(() => import("@/routes/settings").then((m) => ({ default: m.SettingsPage })));

function RouteLoading() {
  return (
    <div className="flex items-center justify-center min-h-[200px]">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--ring)] border-t-transparent" />
    </div>
  );
}

// Root layout
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
const convertRoute = createRoute({ getParentRoute: () => rootRoute, path: "/convert", component: ConvertPage });
const batchRoute = createRoute({ getParentRoute: () => rootRoute, path: "/convert/batch", component: ConvertBatchPage });
const analyzeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/analyze", component: AnalyzePage });
const toolsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/tools", component: ToolsPage });
const aboutRoute = createRoute({ getParentRoute: () => rootRoute, path: "/about", component: AboutPage });
const historyRoute = createRoute({ getParentRoute: () => rootRoute, path: "/history", component: HistoryPage });
const validateRoute = createRoute({ getParentRoute: () => rootRoute, path: "/validate", component: ValidatePage });
const reviewRoute = createRoute({ getParentRoute: () => rootRoute, path: "/review", component: ReviewPage });
const chatRoute = createRoute({ getParentRoute: () => rootRoute, path: "/chat", component: ChatPage });
const portfolioRoute = createRoute({ getParentRoute: () => rootRoute, path: "/portfolio", component: PortfolioPage });
const adviseRoute = createRoute({ getParentRoute: () => rootRoute, path: "/advise", component: AdvisePage });
const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/settings", component: SettingsPage });

const routeTree = rootRoute.addChildren([
  indexRoute,
  convertRoute,
  batchRoute,
  analyzeRoute,
  toolsRoute,
  aboutRoute,
  historyRoute,
  validateRoute,
  reviewRoute,
  chatRoute,
  portfolioRoute,
  adviseRoute,
  settingsRoute,
]);

const router = createRouter({ routeTree });

export function App() {
  return (
    <ErrorBoundary>
      <RouterProvider router={router} />
    </ErrorBoundary>
  );
}
