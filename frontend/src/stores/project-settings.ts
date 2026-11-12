import { create } from "zustand";
import { persist } from "zustand/middleware";
import { safeStorage } from "@/stores/safe-storage";

/**
 * Where each project's generated code reads and writes tables. Every project
 * starts from the default in Settings; setting it on a project's Convert step
 * changes that project only.
 */
interface TableLocation {
  catalogName: string;
  schemaName: string;
}

interface ProjectSettingsState {
  byProject: Record<string, TableLocation>;
  setLocation: (projectId: string, location: TableLocation) => void;
  forget: (projectId: string) => void;
}

export const useProjectSettingsStore = create<ProjectSettingsState>()(
  persist(
    (set) => ({
      byProject: {},
      setLocation: (projectId, location) => set((s) => ({ byProject: { ...s.byProject, [projectId]: location } })),
      forget: (projectId) =>
        set((s) => {
          const next = { ...s.byProject };
          delete next[projectId];
          return { byProject: next };
        }),
    }),
    { name: "a2d-project-settings", storage: safeStorage },
  ),
);
