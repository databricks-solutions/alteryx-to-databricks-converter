import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";

interface NextStepLink {
  to: string;
  label: string;
}

/**
 * A "here's what to do next" callout shown after a result-bearing screen, so a
 * page hands the user onward through the migration flow instead of dead-ending.
 */
export function NextStep({ prompt, links }: { prompt: string; links: NextStepLink[] }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--ring)]/30 bg-[var(--ring)]/5 px-4 py-3 text-sm">
      <ArrowRight className="h-4 w-4 shrink-0 text-[var(--ring)]" />
      <span className="text-[var(--fg)]">{prompt}</span>
      <div className="ml-auto flex flex-wrap gap-4">
        {links.map((l) => (
          <Link
            key={l.to}
            to={l.to}
            className="font-medium text-[var(--ring)] hover:underline whitespace-nowrap"
          >
            {l.label} →
          </Link>
        ))}
      </div>
    </div>
  );
}
