import { create } from "zustand";
import type { FileResult, BatchMetrics } from "@/lib/api";

interface BatchStore {
  jobId: string | null;
  status: "idle" | "uploading" | "running" | "completed" | "error";
  progress: number;
  total: number;
  currentFilename: string;
  fileResults: FileResult[];
  batchMetrics: BatchMetrics | null;
  errorsByKind: Record<string, number> | null;
  errorMessage: string | null;
  ws: WebSocket | null;

  startJob: (jobId: string, total: number) => void;
  connectWs: (jobId: string) => void;
  disconnect: () => void;
  reset: () => void;
}

const MAX_RETRIES = 3;

// Incremented on every connect/disconnect so stale socket callbacks can be ignored.
let connectionGeneration = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

function clearRetryTimer() {
  if (retryTimer !== null) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
}

export const useBatchStore = create<BatchStore>((set, get) => ({
  jobId: null,
  status: "idle",
  progress: 0,
  total: 0,
  currentFilename: "",
  fileResults: [],
  batchMetrics: null,
  errorsByKind: null,
  errorMessage: null,
  ws: null,

  startJob: (jobId, total) =>
    set({
      jobId,
      status: "running",
      progress: 0,
      total,
      fileResults: [],
      batchMetrics: null,
      errorsByKind: null,
      errorMessage: null,
    }),

  connectWs: (jobId) => {
    // Close existing connection before creating a new one
    const { ws: existingWs } = get();
    if (existingWs) {
      existingWs.close();
      set({ ws: null });
    }

    // A connection generation, so events from a socket we've already replaced are
    // ignored. Previously any closing socket ran `set({ ws: null })` even when a
    // newer one was live, and retry timers were never cleared — so a reconnect could
    // null out the active socket, and a disconnect/reset left a pending timer that
    // reopened a connection the user had stopped.
    connectionGeneration += 1;
    const generation = connectionGeneration;
    const isStale = () => generation !== connectionGeneration;

    clearRetryTimer();
    let retryCount = 0;

    function connect() {
      if (isStale()) return;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${proto}//${location.host}/api/ws/batch/${jobId}`;
      const ws = new WebSocket(wsUrl);

      ws.onmessage = (event) => {
        if (isStale()) return;
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch {
          console.warn("Failed to parse WebSocket message:", event.data);
          return;
        }
        if (msg.type === "progress") {
          set({ progress: msg.current, currentFilename: msg.filename });
        } else if (msg.type === "file_complete") {
          set((state) => ({
            fileResults: [...state.fileResults, msg as FileResult],
            progress: state.fileResults.length + 1,
          }));
        } else if (msg.type === "batch_complete") {
          set({
            status: "completed",
            batchMetrics: msg.batch_metrics,
            errorsByKind: msg.errors_by_kind,
            fileResults: msg.file_results,
          });
          ws.close();
        } else if (msg.type === "error") {
          set({
            status: "error",
            errorMessage: msg.message || "Batch processing failed",
          });
          ws.close();
        }
      };

      ws.onerror = () => {
        if (isStale()) return;
        const { status: currentStatus } = get();
        if (currentStatus === "completed" || currentStatus === "error") return;

        if (retryCount < MAX_RETRIES) {
          retryCount++;
          const delay = Math.min(1000 * Math.pow(2, retryCount - 1), 8000);
          retryTimer = setTimeout(connect, delay);
        } else {
          set({
            status: "error",
            errorMessage: "Lost connection to server after multiple retries",
          });
        }
      };

      // Only clear the stored socket if this is still the current connection.
      ws.onclose = () => {
        if (isStale()) return;
        set({ ws: null });
      };

      set({ ws });
    }

    connect();
  },

  disconnect: () => {
    // Invalidate in-flight sockets and cancel any pending retry, otherwise a timer
    // scheduled before disconnect would reopen a connection the user stopped.
    connectionGeneration += 1;
    clearRetryTimer();
    const { ws } = get();
    if (ws) ws.close();
    set({ ws: null });
  },

  reset: () => {
    // Same reasoning as disconnect: a pending retry must not outlive a reset.
    connectionGeneration += 1;
    clearRetryTimer();
    const { ws } = get();
    if (ws) ws.close();
    set({
      jobId: null,
      status: "idle",
      progress: 0,
      total: 0,
      currentFilename: "",
      fileResults: [],
      batchMetrics: null,
      errorsByKind: null,
      errorMessage: null,
      ws: null,
    });
  },
}));
