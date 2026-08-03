import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type ChatSession, type FormatId } from "@/lib/api";

/** Whether the assistant is available (an FMAPI endpoint is configured). */
export function useChatStatus() {
  return useQuery({
    queryKey: ["chat-status"],
    queryFn: api.chatStatus,
    staleTime: 60_000,
  });
}

export function useChatStart() {
  return useMutation<ChatSession, Error, { file: File; outputFormat?: FormatId }>({
    mutationFn: ({ file, outputFormat }) => api.chatStart(file, outputFormat),
  });
}

export function useChatSend() {
  return useMutation<{ session_id: string; reply: string }, Error, { sessionId: string; message: string }>({
    mutationFn: ({ sessionId, message }) => api.chatSend(sessionId, message),
  });
}

export function useChatReport() {
  return useMutation<string, Error, { sessionId: string; answers?: Record<string, string> }>({
    mutationFn: ({ sessionId, answers }) => api.chatReport(sessionId, answers),
  });
}
