import { useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { MarkdownBlock } from "@/components/shared/markdown-block";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useChatReport, useChatSend, useChatStart, useChatStatus } from "@/hooks/use-chat";
import { useToastStore } from "@/stores/toast";
import type { ChatMessage, FormatId, MigrationContext } from "@/lib/api";
import { saveAs } from "file-saver";
import { Play, Loader2, RotateCcw, Send, FileDown, Bot, User, Info } from "lucide-react";

const DEPLOY_VARIANT: Record<MigrationContext["deploy_status"], "success" | "warning" | "destructive"> = {
  ready: "success",
  needs_review: "warning",
  cannot_deploy: "destructive",
};

const DEPLOY_LABEL: Record<MigrationContext["deploy_status"], string> = {
  ready: "Ready to deploy",
  needs_review: "Needs review",
  cannot_deploy: "Cannot deploy as-is",
};

export function ChatPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [outputFormat, setOutputFormat] = useState<FormatId>("pyspark");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [context, setContext] = useState<MigrationContext | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [questions, setQuestions] = useState<string[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [showReportForm, setShowReportForm] = useState(false);

  const addToast = useToastStore((s) => s.add);
  const status = useChatStatus();
  const start = useChatStart();
  const send = useChatSend();
  const report = useChatReport();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the transcript pinned to the newest message.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const enabled = status.data?.enabled ?? false;

  const handleStart = () => {
    if (files.length === 0) return;
    start.mutate(
      { file: files[0], outputFormat },
      {
        onSuccess: (session) => {
          setSessionId(session.session_id);
          setContext(session.context);
          setMessages(session.messages);
          setQuestions(session.clarifying_questions);
        },
      },
    );
  };

  const handleSend = () => {
    const text = draft.trim();
    if (!text || !sessionId || send.isPending) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setDraft("");
    send.mutate(
      { sessionId, message: text },
      {
        onSuccess: ({ reply }) => setMessages((m) => [...m, { role: "assistant", content: reply }]),
        onError: (err) => {
          addToast(err.message, "error");
          // Drop the optimistic message and restore it to the composer. Leaving
          // it in the transcript with no reply implies it was delivered.
          setMessages((m) => m.slice(0, -1));
          setDraft(text);
        },
      },
    );
  };

  const handleGenerateReport = () => {
    if (!sessionId) return;
    report.mutate(
      { sessionId, answers },
      {
        onSuccess: (markdown) => {
          const name = `${context?.workflow_name ?? "workflow"}_suggestions.md`;
          saveAs(new Blob([markdown], { type: "text/markdown;charset=utf-8" }), name);
          addToast("Suggestions report downloaded", "success");
          setShowReportForm(false);
        },
        onError: (err) => addToast(err.message, "error"),
      },
    );
  };

  const handleReset = () => {
    setSessionId(null);
    setContext(null);
    setMessages([]);
    setFiles([]);
    setQuestions([]);
    setAnswers({});
    setShowReportForm(false);
    start.reset();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Migration Assistant"
        description="Discuss the migration, ask why the converter made each choice, and generate downloadable suggestion notes"
      >
        {sessionId && (
          <Button variant="secondary" size="sm" onClick={handleReset}>
            <RotateCcw className="h-4 w-4" />
            New Session
          </Button>
        )}
      </PageHeader>

      {/* Advisory-only notice — set expectations before anything else. */}
      <div className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 text-xs text-[var(--fg-muted)]">
        <Info className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          The assistant is <strong>advisory only</strong>. It can explain the conversion and suggest
          implementations for gaps, but it never modifies your generated code — suggestions arrive as a
          separate Markdown document.
        </span>
      </div>

      {/* Opt-in gate */}
      {!status.isLoading && !enabled && (
        <div className="rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm">
          <p className="font-medium text-[var(--fg)]">AI features are not enabled</p>
          <p className="mt-1 text-[var(--fg-muted)]">
            The assistant needs a Databricks Foundation Model API endpoint. Set{" "}
            <code className="rounded bg-[var(--bg-sidebar)] px-1 py-0.5 font-mono text-xs">
              A2D_FMAPI_ENDPOINT
            </code>{" "}
            on the server (and{" "}
            <code className="rounded bg-[var(--bg-sidebar)] px-1 py-0.5 font-mono text-xs">
              A2D_FMAPI_TOKEN
            </code>{" "}
            if it requires a token), then reload. Conversion itself never requires a model.
          </p>
        </div>
      )}

      {/* Upload */}
      {enabled && !sessionId && (
        <div className="space-y-4">
          <FileDropzone files={files} onFilesChange={setFiles} />
          <div className="flex items-center gap-3">
            <label htmlFor="chat-format" className="text-sm text-[var(--fg-muted)]">
              Target format
            </label>
            <select
              id="chat-format"
              value={outputFormat}
              onChange={(e) => setOutputFormat(e.target.value as FormatId)}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-1.5 text-sm text-[var(--fg)]"
            >
              <option value="pyspark">PySpark</option>
              <option value="dlt">Spark Declarative Pipelines</option>
              <option value="sql">Databricks SQL</option>
              <option value="lakeflow">Lakeflow</option>
            </select>
            <Button onClick={handleStart} disabled={files.length === 0 || start.isPending}>
              {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Start Discussion
            </Button>
          </div>
          {start.isError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {start.error.message}
            </div>
          )}
        </div>
      )}

      {/* Session */}
      {sessionId && context && (
        <div className="space-y-4">
          {/* Migration facts */}
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <span className="font-semibold text-[var(--fg)]">{context.workflow_name}</span>
            <Badge variant={DEPLOY_VARIANT[context.deploy_status]}>
              {DEPLOY_LABEL[context.deploy_status]}
            </Badge>
            <span className="text-xs text-[var(--fg-muted)]">
              {context.node_count} nodes · {context.summary.total_gaps} gap(s)
              {context.summary.blocking_gaps > 0 && ` · ${context.summary.blocking_gaps} blocking`}
              {context.coverage !== null && ` · ${context.coverage.toFixed(1)}% coverage`}
            </span>
            <div className="ml-auto">
              <Button size="sm" variant="secondary" onClick={() => setShowReportForm((v) => !v)}>
                <FileDown className="h-4 w-4" />
                Generate report
              </Button>
            </div>
          </div>

          {/* Clarifying questions before report generation */}
          {showReportForm && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 space-y-3">
              <p className="text-sm text-[var(--fg-muted)]">
                Answering these makes the suggestions fit your target environment. All optional.
              </p>
              {questions.map((q) => (
                <div key={q} className="space-y-1">
                  <label htmlFor={q} className="block text-xs font-medium text-[var(--fg)]">
                    {q}
                  </label>
                  <input
                    id={q}
                    value={answers[q] ?? ""}
                    onChange={(e) => setAnswers((a) => ({ ...a, [q]: e.target.value }))}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-sidebar)] px-3 py-1.5 text-sm text-[var(--fg)]"
                  />
                </div>
              ))}
              <div className="flex gap-2">
                <Button size="sm" onClick={handleGenerateReport} disabled={report.isPending}>
                  {report.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <FileDown className="h-4 w-4" />
                  )}
                  Download Markdown
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setShowReportForm(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {/* Transcript */}
          <div
            ref={scrollRef}
            className="h-[52vh] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 space-y-4"
          >
            {messages.map((m, i) => (
              <div key={i} className="flex gap-3">
                <div
                  className={
                    m.role === "assistant"
                      ? "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--ring)]/10 text-[var(--ring)]"
                      : "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--border)] text-[var(--fg-muted)]"
                  }
                >
                  {m.role === "assistant" ? <Bot className="h-4 w-4" /> : <User className="h-4 w-4" />}
                </div>
                <div className="min-w-0 flex-1">
                  <MarkdownBlock content={m.content} />
                </div>
              </div>
            ))}
            {send.isPending && (
              <div className="flex items-center gap-2 text-xs text-[var(--fg-muted)]">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Thinking…
              </div>
            )}
          </div>

          {/* Composer */}
          <div className="flex gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              rows={2}
              placeholder="Ask why a node converted the way it did, or how to handle a gap… (Enter to send)"
              className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--fg)]"
            />
            <Button onClick={handleSend} disabled={!draft.trim() || send.isPending}>
              <Send className="h-4 w-4" />
              Send
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
