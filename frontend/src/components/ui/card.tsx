import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Card({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6 shadow-sm",
        className,
      )}
      {...props}
    />
  );
}
