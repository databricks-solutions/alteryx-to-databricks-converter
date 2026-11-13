import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  /** Small line above the title — on a step page, which project and step this is. */
  eyebrow?: ReactNode;
  /** Page-level actions (Export and the like). Always top right, on every page. */
  children?: ReactNode;
}

export function PageHeader({ title, description, eyebrow, children }: PageHeaderProps) {
  return (
    <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        {eyebrow && <div className="mb-1 text-xs font-medium text-[var(--fg-muted)]">{eyebrow}</div>}
        <h1 className="text-2xl font-bold text-[var(--fg)]">{title}</h1>
        {description && (
          <p className="mt-1 max-w-3xl text-sm text-[var(--fg-muted)]">{description}</p>
        )}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}
