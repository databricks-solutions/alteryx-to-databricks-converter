import { create } from "zustand";
import type { FileResult, BatchMetrics } from "@/lib/api";

interface BatchStore {
  jobId: string | null;
  /** The project the running/finished job belongs to, so a screen only shows its own. */
  projectId: string | null;
  status: "idle" | "uploading" | "running" | "completed" | "error";
  progress: number;
  total: number;
  currentFilename: string;
  fileResults: FileResult[];
  batchMetrics: BatchMetrics | null;
  errorsByKind: Record<string, number> | null;
  errorMessage: string | null;
  ws: WebSocket | null;
  /** The finished job whose results were already recorded on its project, so
   * revisiting Convert doesn't record (or announce) them again. */
  recordedJobId: string | null;
  markRecorded: (jobId: string) => void;

  startJob: (jobId: string, total: number, projectId?: string | null) => void;
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
  projectId: null,
  status: "idle",
  progress: 0,
  total: 0,
  currentFilename: "",
  fileResults: [],
  batchMetrics: null,
  errorsByKind: null,
  errorMessage: null,
  ws: null,
  recordedJobId: null,
  markRecorded: (jobId) => set({ recordedJobId: jobId }),

  startJob: (jobId, total, projectId = null) =>
    set({
      jobId,
      projectId,
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
          // A reconnect replays results already received; keep one per file.
          set((state) => {
            const result = msg as FileResult;
            const key = result.source_file_name ?? result.file_name;
            const others = state.fileResults.filter((fr) => (fr.source_file_name ?? fr.file_name) !== key);
            const fileResults = [...others, result];
            return { fileResults, progress: fileResults.length };
          });
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

      // A dropped connection while the job is still running (an error, or a
      // clean close such as a server restart) reconnects with backoff, then
      // reports, so progress never hangs at "running" forever.
      let retryScheduled = false;
      const retryOrFail = () => {
        if (isStale() || retryScheduled) return;
        const { status: currentStatus } = get();
        if (currentStatus !== "running") return;
        if (retryCount < MAX_RETRIES) {
          retryCount++;
          retryScheduled = true;
          const delay = Math.min(1000 * Math.pow(2, retryCount - 1), 8000);
          retryTimer = setTimeout(connect, delay);
        } else {
          set({
            status: "error",
            errorMessage: "Lost the connection to the server. The conversion may still be running; reload to check.",
          });
        }
      };

      ws.onerror = retryOrFail;

      // Only clear the stored socket if this is still the current connection.
      ws.onclose = () => {
        if (isStale()) return;
        set({ ws: null });
        retryOrFail();
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
      projectId: null,
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
