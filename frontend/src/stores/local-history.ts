import { create } from "zustand";
import type { ConversionResult } from "@/lib/api";

export interface LocalHistoryItem {
  id: string;
  workflow_name: string;
  output_format: string;
  created_at: string;
  node_count: number;
  edge_count: number;
  coverage_percentage: number | null;
  result: ConversionResult;
}

interface LocalHistoryStore {
  items: LocalHistoryItem[];
  add: (result: ConversionResult) => void;
  remove: (id: string) => void;
  get: (id: string) => LocalHistoryItem | undefined;
}

const STORAGE_KEY = "a2d-local-history";
const MAX_ITEMS = 50;

function loadItems(): LocalHistoryItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveItems(items: LocalHistoryItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)));
  } catch {
    // localStorage full — silently fail
  }
}

let idCounter = Date.now();

function bestCoverage(result: ConversionResult): number | null {
  const best = result.best_format ? result.formats[result.best_format] : null;
  const cov = best?.stats.coverage_percentage;
  return typeof cov === "number" ? cov : null;
}

export const useLocalHistoryStore = create<LocalHistoryStore>((set, get) => ({
  items: loadItems(),

  add: (result) => {
    const item: LocalHistoryItem = {
      id: String(++idCounter),
      workflow_name: result.workflow_name,
      output_format: result.best_format || "multi",
      created_at: new Date().toISOString(),
      node_count: result.node_count,
      edge_count: result.edge_count,
      coverage_percentage: bestCoverage(result),
      result,
    };
    const updated = [item, ...get().items].slice(0, MAX_ITEMS);
    saveItems(updated);
    set({ items: updated });
  },

  remove: (id) => {
    const updated = get().items.filter((i) => i.id !== id);
    saveItems(updated);
    set({ items: updated });
  },

  get: (id) => get().items.find((i) => i.id === id),
}));
