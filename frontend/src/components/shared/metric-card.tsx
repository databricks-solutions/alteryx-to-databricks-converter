import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { Card } from "@/components/ui/card";

interface MetricCardProps {
  label: string;
  value: number;
  suffix?: string;
  icon?: React.ReactNode;
}

export function MetricCard({ label, value, suffix = "", icon }: MetricCardProps) {
  const [displayed, setDisplayed] = useState(0);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (value === 0) {
      setDisplayed(0);
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
        </div>
      </Card>
    </motion.div>
  );
}
