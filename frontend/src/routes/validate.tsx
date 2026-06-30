import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { ValidateResponse } from "@/lib/api";
import { CheckCircle, XCircle, Loader2, Play, Trash2 } from "lucide-react";

export function ValidatePage() {
  const [code, setCode] = useState("");
  const [result, setResult] = useState<ValidateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleValidate = async () => {
    if (!code.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.validate(code);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Validation failed");
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setCode("");
    setResult(null);
    setError(null);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Validate Code"
        description="Check syntax of converted workflows"
      >
        {result && (
          <Button variant="ghost" size="sm" onClick={handleClear}>
            <Trash2 className="h-4 w-4" />
            Clear
          </Button>
        )}
      </PageHeader>

      {/* Code input */}
      <Card>
        <h3 className="text-sm font-semibold text-[var(--fg)] mb-3">
          Paste Generated Code
        </h3>
        <textarea
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Paste your generated Python / PySpark code here..."
          className="w-full h-64 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm font-mono text-[var(--fg)] placeholder:text-[var(--fg-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)] resize-y"
          aria-label="Code to validate"
        />
        <div className="flex items-center justify-between mt-3">
          <span className="text-xs text-[var(--fg-muted)]">
            {code.split("\n").length} lines
          </span>
          <Button
            onClick={handleValidate}
            disabled={!code.trim() || loading}
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Validate Syntax
          </Button>
        </div>
      </Card>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Validation results */}
      {result && (
        <Card>
          <div className="flex items-center gap-3 mb-4">
            {result.all_valid ? (
              <>
                <CheckCircle className="h-6 w-6 text-green-500" />
                <div>
                  <h3 className="text-sm font-semibold text-[var(--fg)]">Syntax Valid</h3>
                  <p className="text-xs text-[var(--fg-muted)]">
                    No syntax errors found. Code is ready for Databricks.
                  </p>
                </div>
                <Badge variant="success" className="ml-auto">PASS</Badge>
              </>
            ) : (
              <>
                <XCircle className="h-6 w-6 text-red-500" />
                <div>
                  <h3 className="text-sm font-semibold text-[var(--fg)]">Syntax Errors Found</h3>
                  <p className="text-xs text-[var(--fg-muted)]">
                    Fix the errors below before deploying to Databricks.
                  </p>
                </div>
                <Badge variant="destructive" className="ml-auto">FAIL</Badge>
              </>
            )}
          </div>

          {result.results.map((r, i) => (
            <div key={i}>
              {r.errors.length > 0 && (
                <div className="space-y-2">
                  {r.errors.map((err, j) => (
                    <div
                      key={j}
                      className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm font-mono text-destructive"
                    >
                      {err}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </Card>
      )}

      {/* Tips */}
      {!result && !loading && (
        <Card className="bg-[var(--bg-sidebar)]">
          <h3 className="text-sm font-semibold text-[var(--fg)] mb-2">Tips</h3>
          <ul className="text-xs text-[var(--fg-muted)] space-y-1 list-disc list-inside">
            <li>Paste the generated PySpark or Spark Declarative Pipelines code from the Convert page</li>
            <li>Databricks notebook magic commands (%sql, %pip) are automatically handled</li>
            <li>SQL validation is not yet supported — only Python syntax is checked</li>
            <li>For full data validation, run the generated code against sample data in Databricks</li>
          </ul>
        </Card>
      )}
    </div>
  );
}
