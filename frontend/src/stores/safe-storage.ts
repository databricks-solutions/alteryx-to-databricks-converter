import { createJSONStorage } from "zustand/middleware";

/**
 * localStorage for zustand's persist middleware that never throws. A full
 * quota (large cached reports) or a blocked storage would otherwise throw out of
 * a state update after the work itself succeeded, and the view would show an
 * error next to data it actually has.
 */
export const safeStorage = createJSONStorage(() => ({
  getItem: (name: string) => {
    try {
      return localStorage.getItem(name);
    } catch {
      return null;
    }
  },
  setItem: (name: string, value: string) => {
    try {
      localStorage.setItem(name, value);
    } catch (e) {
      console.warn(`Could not save ${name} to localStorage`, e);
    }
  },
  removeItem: (name: string) => {
    try {
      localStorage.removeItem(name);
    } catch {
      /* ignore */
    }
  },
}));
