import { useToastStore } from "@/stores/toast";
import { motion, AnimatePresence } from "motion/react";
import { CheckCircle, XCircle, Info, X } from "lucide-react";

const icons = {
  success: <CheckCircle className="h-4 w-4 text-green-500" />,
  error: <XCircle className="h-4 w-4 text-red-500" />,
  info: <Info className="h-4 w-4 text-blue-500" />,
};

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm" aria-live="polite" role="status">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.95 }}
            className="flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 shadow-lg text-sm text-[var(--fg)]"
          >
            {icons[t.type]}
            <span className="flex-1">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="text-[var(--fg-muted)] hover:text-[var(--fg)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
