import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * The last saved project opened, remembered across reloads.
 *
 * The URL (`/p/<id>/...`) decides which project a screen shows. Nothing is ever
 * auto-selected from this value: it only feeds the "Resume" card on the
 * Projects page and the redirects from old bookmarks (`/assess` and so on).
 * Session-only projects aren't remembered, since they don't survive a reload.
 */
interface ProjectStore {
  lastProjectId: string | null;
  setLastProject: (id: string | null) => void;
}

export const useProjectStore = create<ProjectStore>()(
  persist(
    (set) => ({
      lastProjectId: null,
      setLastProject: (id) => set({ lastProjectId: id }),
    }),
    { name: "a2d-last-project" },
  ),
);
