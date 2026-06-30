import { create } from "zustand";

export type BooleanSettingKey =
  | "includeComments"
  | "includeExpressionAudit"
  | "includePerformanceHints"
  | "generateDdl"
  | "generateDab"
  | "expandMacros";

interface SettingsStore {
  catalogName: string;
  schemaName: string;
  includeComments: boolean;
  includeExpressionAudit: boolean;
  includePerformanceHints: boolean;
  generateDdl: boolean;
  generateDab: boolean;
  expandMacros: boolean;
  setCatalogName: (v: string) => void;
  setSchemaName: (v: string) => void;
  setBooleanSetting: (key: BooleanSettingKey, value: boolean) => void;
  resetToDefaults: () => void;
}

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(`a2d-${key}`);
    return v !== null ? JSON.parse(v) : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  localStorage.setItem(`a2d-${key}`, JSON.stringify(value));
}

export const useSettingsStore = create<SettingsStore>((set) => {
  const setBooleanSetting = (key: BooleanSettingKey, value: boolean) => {
    save(key, value);
    set({ [key]: value });
  };

  return {
    catalogName: load("catalogName", "main"),
    schemaName: load("schemaName", "default"),
    includeComments: load("includeComments", true),
    includeExpressionAudit: load("includeExpressionAudit", true),
    includePerformanceHints: load("includePerformanceHints", true),
    generateDdl: load("generateDdl", false),
    generateDab: load("generateDab", false),
    expandMacros: load("expandMacros", false),

    setCatalogName: (v) => {
      save("catalogName", v);
      set({ catalogName: v });
    },
    setSchemaName: (v) => {
      save("schemaName", v);
      set({ schemaName: v });
    },
    setBooleanSetting,
    resetToDefaults: () => {
      const defaults = {
        catalogName: "main",
        schemaName: "default",
        includeComments: true,
        includeExpressionAudit: true,
        includePerformanceHints: true,
        generateDdl: false,
        generateDab: false,
        expandMacros: false,
      };
      for (const [k, v] of Object.entries(defaults)) {
        save(k, v);
      }
      set(defaults);
    },
  };
});
