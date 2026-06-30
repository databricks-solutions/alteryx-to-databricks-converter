import { type ReactNode } from "react";
import { motion, AnimatePresence } from "motion/react";

interface PageTransitionProps {
  children: ReactNode;
  routeKey: string;
}

export function PageTransition({ children, routeKey }: PageTransitionProps) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={routeKey}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
