import { create } from "zustand";

export interface Toast {
  id: string;
  message: string;
  type: "success" | "error" | "info";
}

interface ToastStore {
  toasts: Toast[];
  add: (message: string, type?: Toast["type"]) => void;
  dismiss: (id: string) => void;
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  add: (message, type = "info") => {
    const id = crypto.randomUUID();
    set((s) => {
      const next = [...s.toasts, { id, message, type }];
      // Keep at most 5 visible toasts — drop oldest when over limit
      return { toasts: next.length > 5 ? next.slice(-5) : next };
    });
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 4000);
  },
  dismiss: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
