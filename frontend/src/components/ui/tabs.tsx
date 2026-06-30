import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/cn";

export const Tabs = TabsPrimitive.Root;

export function TabsList({
  className,
  ...props
}: TabsPrimitive.TabsListProps) {
  return (
    <TabsPrimitive.List
      className={cn(
        "flex max-w-full items-center gap-1 overflow-x-auto rounded-lg bg-[var(--bg-sidebar)] p-1",
        "[scrollbar-width:thin]",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  className,
  ...props
}: TabsPrimitive.TabsTriggerProps) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium text-[var(--fg-muted)] transition-colors",
        "hover:text-[var(--fg)] data-[state=active]:bg-[var(--bg)] data-[state=active]:text-[var(--fg)] data-[state=active]:shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({
  className,
  ...props
}: TabsPrimitive.TabsContentProps) {
  return (
    <TabsPrimitive.Content
      className={cn("mt-4 focus-visible:outline-none", className)}
      {...props}
    />
  );
}
