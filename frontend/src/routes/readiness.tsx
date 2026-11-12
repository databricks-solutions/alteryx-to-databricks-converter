import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useReadinessPrefill,
  useReadinessQuestions,
  useReadinessScore,
} from "@/hooks/use-readiness";
import { useEstateStore } from "@/stores/estate";
import { useProjectContext } from "@/hooks/use-project-context";
import type { ReadinessResult } from "@/lib/api";
import { ClipboardList, Loader2, Pencil, Info, Lightbulb } from "lucide-react";

function tierTone(tier: string): "good" | "mid" | "bad" {
  if (tier === "Advanced" || tier === "Ready") return "good";
  if (tier === "Developing") return "mid";
  return "bad";
}

function scoreColor(score: number): string {
  return score >= 70 ? "#22c55e" : score >= 45 ? "#eab308" : "#ef4444";
}

// In-progress answers persist per project, so a half-filled questionnaire
// survives navigation and reloads. The values that came from the estate prefill
// are kept separately, so a later prefill (after files change) can refresh them
// without overwriting anything you changed yourself.
interface SavedAnswers {
  answers: Record<string, string>;
  prefilled: Record<string, string>;
}
const answersKey = (projectId: string) => `a2d-readiness-answers:${projectId}`;
function loadAnswers(projectId: string | null): SavedAnswers {
  const empty = { answers: {}, prefilled: {} };
  if (!projectId) return empty;
  try {
    const raw = localStorage.getItem(answersKey(projectId));
    if (!raw) return empty;
    const parsed = JSON.parse(raw);
    // Older saves were just the answers map.
    return "answers" in parsed ? parsed : { answers: parsed, prefilled: {} };
  } catch {
    return empty;
  }
}
function saveAnswers(projectId: string | null, saved: SavedAnswers) {
  if (!projectId) return;
  try {
    localStorage.setItem(answersKey(projectId), JSON.stringify(saved));
  } catch {
    /* localStorage unavailable — non-fatal */
  }
}

/** The organizational readiness self-assessment for the open project. The
 * estate questions are pre-answered from the project's workflows. */
export function ReadinessPage() {
  const ctx = useProjectContext();
  const projectId = ctx.projectId;
  const { data: bank, isLoading } = useReadinessQuestions();
  const prefill = useReadinessPrefill();
  const scoreMut = useReadinessScore();
  const stored = useEstateStore((s) => (projectId ? s.byProject[projectId]?.readiness : undefined));
  const saveResult = useEstateStore((s) => s.saveResult);
  const clearResult = useEstateStore((s) => s.clearResult);
  const [{ answers, prefilled }, setSaved] = useState<SavedAnswers>(() => loadAnswers(projectId));
  const prefilledFor = useRef<string | null>(null);
  const result = stored?.data ?? null;
  // The score is kept when files change (it's your answers), but say so.
  const filesChanged = stored != null && stored.signature !== ctx.signature;

  useEffect(() => {
    saveAnswers(projectId, { answers, prefilled });
  }, [projectId, answers, prefilled]);

  // Pre-answer the estate questions from the project's files, once per file set.
  // A question you answered yourself keeps your answer.
  const { mutate: runPrefill } = prefill;
  useEffect(() => {
    if (!ctx.source || ctx.workflows.length === 0 || prefilledFor.current === ctx.signature) return;
    prefilledFor.current = ctx.signature;
    runPrefill(
      { source: ctx.source },
      {
        onSuccess: (res) =>
          setSaved((cur) => {
            const next = { ...cur.answers };
            for (const [q, v] of Object.entries(res.answers)) {
              const untouched = next[q] === undefined || next[q] === cur.prefilled[q];
              if (untouched) next[q] = v;
            }
            return { answers: next, prefilled: { ...cur.prefilled, ...res.answers } };
          }),
      },
    );
  }, [ctx.source, ctx.workflows.length, ctx.signature, runPrefill]);

  const totalQuestions = bank?.dimensions.reduce((n, d) => n + d.questions.length, 0) ?? 0;
  const answeredCount = Object.values(answers).filter((v) => v).length;

  const pick = (qid: string, value: string) => setSaved((cur) => ({ ...cur, answers: { ...cur.answers, [qid]: value } }));

  const submit = () => {
    if (answeredCount === 0 || !projectId) return;
    scoreMut.mutate(
      { answers },
      { onSuccess: (data) => saveResult(projectId, "readiness", data, ctx.signature) },
    );
  };

  const editAnswers = () => {
    if (projectId) clearResult(projectId, "readiness");
    scoreMut.reset();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 text-xs text-[var(--fg-muted)]">
        <Info className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          A deterministic self-assessment (no AI) of your organization's readiness. Answer what you can — partial
          answers still score.{" "}
          {prefill.isPending
            ? "Pre-answering the estate questions from this project's workflows…"
            : prefill.data
              ? `The estate questions were pre-answered from this project's ${prefill.data.workflow_count} workflow(s); you can change any of them.`
              : null}
        </span>
      </div>

      {result && filesChanged && (
        <p className="rounded-lg border border-warning/30 bg-warning/5 px-4 py-2 text-xs text-[var(--fg-muted)]">
          The project's workflows changed since this score. The estate answers may be different now: choose Edit
          answers and score again to include them.
        </p>
      )}

      {result && (
        <div className="flex justify-end">
          <Button variant="secondary" size="sm" onClick={editAnswers}>
            <Pencil className="h-4 w-4" />
            Edit answers
          </Button>
        </div>
      )}

      {!result && (
        <>
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
