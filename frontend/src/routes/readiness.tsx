import { useState } from "react";
import { motion } from "motion/react";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useReadinessPrefill,
  useReadinessQuestions,
  useReadinessScore,
} from "@/hooks/use-readiness";
import { downloadJson } from "@/lib/portfolio-download";
import type { ReadinessResult } from "@/lib/api";
import { ClipboardList, Loader2, RotateCcw, Download, Info, Wand2, Lightbulb } from "lucide-react";

function tierTone(tier: string): "good" | "mid" | "bad" {
  if (tier === "Advanced" || tier === "Ready") return "good";
  if (tier === "Developing") return "mid";
  return "bad";
}

function scoreColor(score: number): string {
  return score >= 70 ? "#22c55e" : score >= 45 ? "#eab308" : "#ef4444";
}

export function ReadinessPage() {
  const { data: bank, isLoading } = useReadinessQuestions();
  const prefill = useReadinessPrefill();
  const scoreMut = useReadinessScore();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [prefillFiles, setPrefillFiles] = useState<File[]>([]);
  const result = scoreMut.data;

  const totalQuestions = bank?.dimensions.reduce((n, d) => n + d.questions.length, 0) ?? 0;
  const answeredCount = Object.values(answers).filter((v) => v).length;

  const pick = (qid: string, value: string) => setAnswers((a) => ({ ...a, [qid]: value }));

  const runPrefill = () => {
    if (prefillFiles.length === 0) return;
    prefill.mutate(
      { files: prefillFiles },
      { onSuccess: (res) => setAnswers((a) => ({ ...a, ...res.answers })) },
    );
  };

  const submit = () => {
    if (answeredCount === 0) return;
    scoreMut.mutate({ answers });
  };

  const reset = () => {
    scoreMut.reset();
    setAnswers({});
    setPrefillFiles([]);
    prefill.reset();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Migration Readiness"
        description="A smart, Alteryx→Databricks self-assessment — score your readiness and get tailored tips"
      >
        {result && (
          <>
            <Button variant="secondary" size="sm" onClick={() => downloadJson(result, "readiness-assessment.json")}>
              <Download className="h-4 w-4" />
              Export JSON
            </Button>
            <Button variant="secondary" size="sm" onClick={reset}>
              <RotateCcw className="h-4 w-4" />
              Start Over
            </Button>
          </>
        )}
      </PageHeader>

      <div className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 text-xs text-[var(--fg-muted)]">
        <Info className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          A deterministic self-assessment (no AI). Answer what you can — partial answers still score. Distinct from the{" "}
          <strong className="text-[var(--fg)]">Profiler</strong>, which analyzes your workflow files; this scores your{" "}
          organizational readiness.
        </span>
      </div>

      {!result && (
        <>
          {/* Optional smart prefill from the actual estate. */}
          <Card className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <Wand2 className="h-4 w-4 text-[var(--ring)]" />
              <h2 className="text-sm font-semibold text-[var(--fg)]">Prefill from your estate (optional)</h2>
            </div>
            <p className="text-xs text-[var(--fg-muted)]">
              Upload your Alteryx workflows and we'll pre-answer the estate questions from the actual files
              (count, macros, advanced tools). You can still edit every answer.
            </p>
            <FileDropzone files={prefillFiles} onFilesChange={setPrefillFiles} multiple />
            <div className="flex items-center gap-3">
              <Button variant="secondary" size="sm" onClick={runPrefill} disabled={prefillFiles.length === 0 || prefill.isPending}>
                {prefill.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                Prefill estate answers
              </Button>
              {prefill.data && (
                <span className="text-xs text-[var(--fg-muted)]">
                  Pre-filled {Object.keys(prefill.data.answers).length} answer(s) from {prefill.data.workflow_count} workflow(s)
                </span>
              )}
              {prefill.isError && <span className="text-xs text-destructive">{prefill.error.message}</span>}
            </div>
          </Card>

          {/* Questionnaire */}
          {isLoading && <Skeleton className="h-96" />}
          {bank && (
            <div className="space-y-6">
              {bank.dimensions.map((dim) => (
                <Card key={dim.id} className="flex flex-col gap-4">
                  <h2 className="text-sm font-semibold text-[var(--fg)]">{dim.label}</h2>
                  {dim.questions.map((q) => (
                    <div key={q.id} className="border-t border-[var(--border)] pt-4 first:border-0 first:pt-0">
                      <p className="mb-2 text-sm text-[var(--fg)]">{q.prompt}</p>
                      <div className="flex flex-col gap-1.5">
                        {q.options.map((opt) => (
                          <label
                            key={opt.value}
                            className={`flex cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2 text-sm transition-colors ${
                              answers[q.id] === opt.value
                                ? "border-[var(--ring)] bg-[var(--ring)]/10 text-[var(--fg)]"
                                : "border-[var(--border)] text-[var(--fg-muted)] hover:border-[var(--ring)]/40"
                            }`}
                          >
                            <input
                              type="radio"
                              name={q.id}
                              value={opt.value}
                              checked={answers[q.id] === opt.value}
                              onChange={() => pick(q.id, opt.value)}
                              className="h-4 w-4 accent-[var(--ring)]"
                            />
                            {opt.label}
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </Card>
              ))}

              <div className="sticky bottom-4 flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
                <Button onClick={submit} disabled={answeredCount === 0 || scoreMut.isPending}>
                  {scoreMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardList className="h-4 w-4" />}
                  Score readiness
                </Button>
                <span className="text-xs text-[var(--fg-muted)]">
                  {answeredCount}/{totalQuestions} answered
                </span>
                {scoreMut.isError && <span className="text-xs text-destructive">{scoreMut.error.message}</span>}
              </div>
            </div>
          )}
        </>
      )}

      {result && <ReadinessResults result={result} />}
    </div>
  );
}

function ReadinessResults({ result }: { result: ReadinessResult }) {
  const tone = tierTone(result.tier);
  const tierColor = tone === "good" ? "text-green-500" : tone === "mid" ? "text-yellow-500" : "text-red-500";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-6"
    >
      <Card className="flex flex-col items-center gap-1 py-6">
        <p className="text-xs font-medium uppercase tracking-wide text-[var(--fg-muted)]">Overall readiness</p>
        <p className={`text-5xl font-bold ${tierColor}`}>{Math.round(result.overall_score)}</p>
        <Badge variant={tone === "good" ? "success" : tone === "mid" ? "warning" : "destructive"}>{result.tier}</Badge>
        <p className="mt-1 text-xs text-[var(--fg-muted)]">
          {result.answered}/{result.total_questions} questions answered
        </p>
      </Card>

      <Card className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-[var(--fg)]">By dimension</h2>
        {Object.entries(result.dimension_scores).map(([dim, s]) => (
          <div key={dim} className="flex items-center gap-3">
            <span className="w-48 shrink-0 text-sm text-[var(--fg)]">{result.dimension_labels[dim] ?? dim}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--border)]">
              <div className="h-full rounded-full" style={{ width: `${s}%`, backgroundColor: scoreColor(s) }} />
            </div>
            <span className="w-10 shrink-0 text-right text-sm tabular-nums text-[var(--fg)]">{Math.round(s)}</span>
          </div>
        ))}
      </Card>

      {result.tips.length > 0 ? (
        <Card className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-[var(--ring)]" />
            <h2 className="text-sm font-semibold text-[var(--fg)]">
              Recommendations ({result.tips.length}) — weakest first
            </h2>
          </div>
          <div className="space-y-3">
            {result.tips.map((tip) => (
              <div key={tip.question_id} className="border-t border-[var(--border)] pt-3 first:border-0 first:pt-0">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{tip.dimension_label}</Badge>
                  <span className="text-xs text-[var(--fg-muted)]">{tip.answer}</span>
                </div>
                <p className="text-sm text-[var(--fg)]">{tip.tip}</p>
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <Card>
          <p className="text-sm text-green-500">No gaps flagged — your answers indicate strong readiness across the board.</p>
        </Card>
      )}

      {result.unanswered.length > 0 && (
        <p className="text-xs text-[var(--fg-muted)]">
          {result.unanswered.length} question(s) unanswered — the score reflects only what you answered.
        </p>
      )}

      <p className="text-[11px] text-[var(--fg-muted)]">{result.disclaimer}</p>
    </motion.div>
  );
}
