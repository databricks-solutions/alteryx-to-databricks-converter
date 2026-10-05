import { create } from "zustand";

interface ConvertBridgeStore {
  // Incoming hint: set by Analyze/Assess ("convert THIS workflow next"), shown
  // and then cleared by the Convert page. Name only.
  workflowName: string | null;
  setWorkflowName: (name: string) => void;
  clear: () => void;

  // Outgoing handoff: a workflow file passed into a single-file screen (Convert,
  // Advisor, Assistant) so it runs without a re-upload — set either by the
  // Convert page after a conversion, or by the Project screen when launching a
  // stored workflow. In memory only (a File can't be serialized), so it survives
  // navigation within a session, which is the "launch it, now act on it" flow.
  //
  // When the file came from a saved project, the source ids ride along so the
  // destination screen can advance that workflow's lifecycle stage on success.
  handoffFile: File | null;
  handoffName: string | null;
  handoffProjectId: string | null;
  handoffWorkflowId: string | null;
  setHandoff: (file: File, source?: { projectId: string; workflowId: string }) => void;
  clearHandoff: () => void;
}

export const useConvertBridge = create<ConvertBridgeStore>((set) => ({
  workflowName: null,
  setWorkflowName: (name) => set({ workflowName: name }),
  clear: () => set({ workflowName: null }),

  handoffFile: null,
  handoffName: null,
  handoffProjectId: null,
  handoffWorkflowId: null,
  setHandoff: (file, source) =>
    set({
      handoffFile: file,
      handoffName: file.name,
      handoffProjectId: source?.projectId ?? null,
      handoffWorkflowId: source?.workflowId ?? null,
    }),
  clearHandoff: () =>
    set({ handoffFile: null, handoffName: null, handoffProjectId: null, handoffWorkflowId: null }),
}));
