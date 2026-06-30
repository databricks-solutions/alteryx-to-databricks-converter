import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const variants = {
  default: "bg-[var(--ring)]/10 text-[var(--ring)]",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  destructive: "bg-destructive/10 text-destructive",
  secondary: "bg-[var(--border)] text-[var(--fg-muted)]",
};

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: keyof typeof variants;
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
