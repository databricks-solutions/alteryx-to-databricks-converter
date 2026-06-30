import * as ProgressPrimitive from "@radix-ui/react-progress";
import { cn } from "@/lib/cn";

interface ProgressProps {
  value: number;
  className?: string;
}

export function Progress({ value, className }: ProgressProps) {
  return (
    <ProgressPrimitive.Root
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-[var(--border)]",
        className,
      )}
    >
      <ProgressPrimitive.Indicator
        className="h-full bg-[var(--ring)] transition-all duration-300 ease-out rounded-full"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </ProgressPrimitive.Root>
  );
}
