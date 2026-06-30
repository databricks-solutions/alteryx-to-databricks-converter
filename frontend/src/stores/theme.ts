import { create } from "zustand";

type Theme = "light" | "dark";

interface ThemeStore {
  theme: Theme;
  toggle: () => void;
}

// Apply theme class on initial load to prevent flash
const stored = localStorage.getItem("a2d-theme");
const systemPrefersDark = typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
const initialTheme: Theme = stored === "light" || stored === "dark" ? stored : systemPrefersDark ? "dark" : "light";

if (initialTheme === "dark") {
  document.documentElement.classList.add("dark");
} else {
  document.documentElement.classList.remove("dark");
}

export const useThemeStore = create<ThemeStore>((set) => ({
  theme: initialTheme,
  toggle: () =>
    set((state) => {
      const next: Theme = state.theme === "dark" ? "light" : "dark";
      localStorage.setItem("a2d-theme", next);
      if (next === "dark") {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
      return { theme: next };
    }),
}));
