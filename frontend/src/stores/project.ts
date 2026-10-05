import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * The active Migration Project. Only the id is held here (and persisted), so a
 * reload resumes the same project; the project's data is fetched from the server
 * by id. When no project is active the app behaves as it always has — per-visit,
 * in-session stores — so this is purely additive.
 */
interface ProjectStore {
  activeProjectId: string | null;
  setActiveProject: (id: string | null) => void;
}

export const useProjectStore = create<ProjectStore>()(
  persist(
    (set) => ({
      activeProjectId: null,
      setActiveProject: (id) => set({ activeProjectId: id }),
    }),
    { name: "a2d-active-project" },
  ),
);
