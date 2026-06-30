import { type ButtonHTMLAttributes, forwardRef } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/cn";

const variants = {
  default:
    "bg-[var(--ring)] text-white hover:bg-[var(--ring)]/90 shadow-sm",
  secondary:
    "bg-[var(--bg-card)] text-[var(--fg)] border border-[var(--border)] hover:bg-[var(--border)]/50",
  ghost: "hover:bg-[var(--border)]/50 text-[var(--fg-muted)]",
  destructive: "bg-destructive text-white hover:bg-destructive/90",
};

const sizes = {
  sm: "h-8 px-3 text-xs rounded-md",
  md: "h-9 px-4 text-sm rounded-lg",
  lg: "h-10 px-6 text-sm rounded-lg",
  icon: "h-9 w-9 rounded-lg",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", asChild, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-2 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
          variants[variant],
          sizes[size],
          className,
        )}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
