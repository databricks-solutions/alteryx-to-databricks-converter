import { Link, useRouterState } from "@tanstack/react-router";
import {
  Home,
  ArrowRightLeft,
  Layers,
  BarChart3,
  Grid3X3,
  Info,
  Moon,
  Sun,
  Menu,
  X,
  Clock,
  CheckCircle,
  ClipboardCheck,
  MessageSquare,
  Network,
  Gauge,
  Settings,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { useThemeStore } from "@/stores/theme";
import { Button } from "@/components/ui/button";

declare const __BUILD_SHA__: string;
declare const __BUILD_DATE__: string;

interface NavItem {
  to: string;
  label: string;
  icon: typeof Home;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    title: "",
    items: [{ to: "/", label: "Home", icon: Home }],
  },
  {
    title: "Assess",
    items: [
      { to: "/analyze", label: "Analyze", icon: BarChart3 },
      { to: "/portfolio", label: "Portfolio", icon: Network },
      { to: "/tools", label: "Tools", icon: Grid3X3 },
    ],
  },
  {
    title: "Migrate",
    items: [
      { to: "/convert", label: "Convert", icon: ArrowRightLeft },
      { to: "/convert/batch", label: "Batch", icon: Layers },
      { to: "/history", label: "History", icon: Clock },
    ],
  },
  {
    title: "Validate",
    items: [
      { to: "/validate", label: "Validate", icon: CheckCircle },
      { to: "/review", label: "Review", icon: ClipboardCheck },
      { to: "/advise", label: "Advisor", icon: Gauge },
    ],
  },
  {
    title: "Assist",
    items: [{ to: "/chat", label: "Assistant", icon: MessageSquare }],
  },
  {
    title: "",
    items: [
      { to: "/settings", label: "Settings", icon: Settings },
      { to: "/about", label: "About", icon: Info },
    ],
  },
];

export function Sidebar() {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggle);
  const [open, setOpen] = useState(false);
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;

  return (
    <>
      {/* Mobile hamburger */}
      <button
        aria-label="Toggle navigation"
        aria-expanded={open}
        className="fixed top-4 left-4 z-50 lg:hidden rounded-lg p-2 bg-[var(--bg-card)] border border-[var(--border)] shadow-sm"
        onClick={() => setOpen(!open)}
      >
        {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {/* Overlay */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col bg-[var(--bg-sidebar)] border-r border-[var(--border)] transition-transform duration-200",
          "lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 py-5 border-b border-[var(--border)]">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--ring)] text-white font-bold text-sm">
            a2d
          </div>
          <div>
            <div className="text-sm font-semibold text-[var(--fg)]">
              Alteryx to Databricks
            </div>
            <div className="text-xs text-[var(--fg-muted)]">
              Migration Accelerator
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {navGroups.map((group, gi) => (
            <div key={gi}>
              {group.title && (
                <div className="px-3 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--fg-muted)]">
                  {group.title}
                </div>
              )}
              {group.items.map(({ to, label, icon: Icon }) => {
                const active = currentPath === to;
                return (
                  <Link
                    key={to}
                    to={to}
                    onClick={() => setOpen(false)}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                      active
                        ? "bg-[var(--ring)]/10 text-[var(--ring)]"
                        : "text-[var(--fg-muted)] hover:bg-[var(--border)]/50 hover:text-[var(--fg)]",
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Theme toggle */}
        <div className="border-t border-[var(--border)] p-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={toggle}
            className="w-full justify-start gap-3"
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </Button>
        </div>

        {/* Build version */}
        <div
          className="border-t border-[var(--border)] px-4 py-2 text-[10px] font-mono text-[var(--fg-muted)]"
          title={__BUILD_DATE__ ? `Built ${__BUILD_DATE__}` : undefined}
        >
          <a
            href={`https://github.com/databricks-solutions/alteryx-to-databricks-converter/commit/${__BUILD_SHA__}`}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-[var(--fg)]"
          >
            build {__BUILD_SHA__}
          </a>
        </div>
      </aside>
    </>
  );
}
