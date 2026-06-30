import { create } from "zustand";

interface ConvertBridgeStore {
  workflowName: string | null;
  setWorkflowName: (name: string) => void;
  clear: () => void;
}

export const useConvertBridge = create<ConvertBridgeStore>((set) => ({
  workflowName: null,
  setWorkflowName: (name) => set({ workflowName: name }),
  clear: () => set({ workflowName: null }),
}));
