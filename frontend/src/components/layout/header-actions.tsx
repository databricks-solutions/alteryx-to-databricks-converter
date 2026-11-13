import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Page-level actions (downloads, "Mark reviewed") always render top right of
 * the step header, even when they belong to a tab deep in the page. The step
 * header owns a slot; a tab puts its actions there with <HeaderActions>.
 */
const SlotContext = createContext<{ slot: HTMLElement | null; setSlot: (el: HTMLElement | null) => void } | null>(
  null,
);

export function HeaderActionsProvider({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return <SlotContext.Provider value={{ slot, setSlot }}>{children}</SlotContext.Provider>;
}

/** The slot itself, rendered by the step header. */
export function HeaderActionsSlot() {
  const ctx = useContext(SlotContext);
  return <div ref={ctx?.setSlot} className="flex flex-wrap items-center gap-2 empty:hidden" />;
}

/** Render ``children`` in the step header's action area. */
export function HeaderActions({ children }: { children: ReactNode }) {
  const ctx = useContext(SlotContext);
  if (!ctx?.slot) return null;
  return createPortal(children, ctx.slot);
}
