import { useState, useEffect } from "react";
import { motion } from "motion/react";
import { Progress } from "@/components/ui/progress";
import { useBatchStore } from "@/stores/batch";
import { Loader2 } from "lucide-react";

export function BatchProgress() {
  const status = useBatchStore((s) => s.status);
  const progress = useBatchStore((s) => s.progress);
  const total = useBatchStore((s) => s.total);
  const currentFilename = useBatchStore((s) => s.currentFilename);
  const [startTime] = useState(() => Date.now());
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (status !== "running") return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [status]);

  if (status !== "running") return null;

  const pct = total > 0 ? (progress / total) * 100 : 0;
  const elapsed = (Date.now() - startTime) / 1000;
  const speed = progress > 0 ? progress / elapsed : 0;
  const remaining = speed > 0 ? Math.ceil((total - progress) / speed) : 0;

  // suppress unused-var lint for tick (forces re-render)
  void tick;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium text-[var(--fg)]">
          <Loader2 className="h-4 w-4 animate-spin text-[var(--ring)]" />
          Converting {progress} of {total}
        </div>
        {progress > 0 && (
          <span className="text-xs text-[var(--fg-muted)]">
            ~{speed.toFixed(1)} files/sec &middot; ~{remaining}s remaining
          </span>
        )}
      </div>
      <Progress value={pct} />
      {currentFilename && (
        <p className="text-xs text-[var(--fg-muted)]">
          Processing: {currentFilename}
        </p>
      )}
    </motion.div>
  );
}
