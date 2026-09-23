import { create } from "zustand";

interface ConvertBridgeStore {
  // Incoming hint: set by Analyze/Assess ("convert THIS workflow next"), shown
  // and then cleared by the Convert page. Name only.
  workflowName: string | null;
  setWorkflowName: (name: string) => void;
  clear: () => void;

  // Outgoing handoff: the workflow file the user just converted, so the Assistant
  // and Advisor can operate on it without forcing a re-upload. In memory only (a
  // File can't be serialized), so it survives navigation within a session but not
  // a full reload — which is exactly the "converted it, now discuss it" flow.
  handoffFile: File | null;
  handoffName: string | null;
  setHandoff: (file: File) => void;
  clearHandoff: () => void;
}

export const useConvertBridge = create<ConvertBridgeStore>((set) => ({
  workflowName: null,
  setWorkflowName: (name) => set({ workflowName: name }),
  clear: () => set({ workflowName: null }),

  handoffFile: null,
  handoffName: null,
  setHandoff: (file) => set({ handoffFile: file, handoffName: file.name }),
  clearHandoff: () => set({ handoffFile: null, handoffName: null }),
}));
