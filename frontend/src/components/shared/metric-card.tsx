import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { Card } from "@/components/ui/card";

interface MetricCardProps {
  label: string;
  value: number;
  suffix?: string;
  icon?: React.ReactNode;
  /**
   * Short definition shown under the number.
   *
   * Figures like "Coverage 92%" and "Confidence 82/100" read as precise
   * measurements when they are scoped counts and heuristics. Keeping the
   * definition adjacent to the value is the point — a tooltip or a separate docs
   * page is too far away to prevent the wrong conclusion.
   */
  hint?: string;
}

export function MetricCard({ label, value, suffix = "", icon, hint }: MetricCardProps) {
  const [displayed, setDisplayed] = useState(0);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (value === 0) {
      setDisplayed(0);
      return;
    }
    // A count-up is decorative motion. CSS can suppress transitions but not a
    // requestAnimationFrame loop, so honour the preference here too and show the
    // final value immediately.
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion) {
      setDisplayed(value);
      return;
    }
    const duration = 600;
    const start = performance.now();

    function animate(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      setDisplayed(Math.round(value * progress));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      } else {
        setDisplayed(value);
      }
    }

    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Card className="flex items-start gap-4">
        {icon && (
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--ring)]/10 text-[var(--ring)]">
            {icon}
          </div>
        )}
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-[var(--fg-muted)]">
            {label}
          </p>
          <p className="text-2xl font-bold text-[var(--fg)] mt-1">
            {Number.isInteger(value) ? displayed : displayed.toFixed(1)}
            {suffix}
          </p>
          {hint && <p className="mt-1 text-[11px] leading-snug text-[var(--fg-muted)]">{hint}</p>}
        </div>
      </Card>
    </motion.div>
  );
}
