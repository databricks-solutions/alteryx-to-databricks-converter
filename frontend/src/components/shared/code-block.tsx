import { useEffect, useId, useRef, useState } from "react";
import { Copy, Check, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getHighlighter } from "@/lib/shiki";
import { useThemeStore } from "@/stores/theme";

const ALLOWED_LANGUAGES = new Set(["python", "sql", "json"]);

interface CodeBlockProps {
  code: string;
  language: string;
  filename?: string;
  highlightLine?: number;
}

export function CodeBlock({ code, language, filename, highlightLine }: CodeBlockProps) {
  const [html, setHtml] = useState("");
  const [copied, setCopied] = useState(false);
  const [showLines, setShowLines] = useState(true);
  const theme = useThemeStore((s) => s.theme);
  const blockId = useId();
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!highlightLine || !containerRef.current) return;
    const target = containerRef.current.querySelector<HTMLDivElement>(
      `[data-line="${highlightLine}"]`,
    );
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.add("a2d-line-flash");
    const t = setTimeout(() => target.classList.remove("a2d-line-flash"), 1200);
    return () => clearTimeout(t);
  }, [highlightLine, html]);

  useEffect(() => {
    let mounted = true;
    getHighlighter()
      .then((highlighter) => {
        if (!mounted) return;
        // Validate language against allowlist to prevent injection
        const lang = ALLOWED_LANGUAGES.has(language) ? language : "json";
        const result = highlighter.codeToHtml(code, {
          lang,
          theme: theme === "dark" ? "github-dark" : "github-light",
        });
        setHtml(result);
      })
      .catch((err) => {
        if (!mounted) return;
        console.warn("Syntax highlighting failed:", err);
        setHtml(`<pre><code>${code.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</code></pre>`);
      });
    return () => {
      mounted = false;
    };
  }, [code, language, theme]);

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadFile = () => {
    const ext = language === "python" ? "py" : language === "sql" ? "sql" : "json";
    const blob = new Blob([code], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || `output.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="rounded-xl border border-[var(--border)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between bg-[var(--bg-sidebar)] px-4 py-2 border-b border-[var(--border)]">
        <span className="text-xs font-medium text-[var(--fg-muted)]">
          {filename || language}
        </span>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="icon"
            aria-label={showLines ? "Hide line numbers" : "Show line numbers"}
            onClick={() => setShowLines(!showLines)}
            className="h-7 w-7"
          >
            <span className="text-[10px] font-mono">#</span>
          </Button>
          <Button variant="ghost" size="icon" aria-label="Copy code" onClick={copyToClipboard} className="h-7 w-7">
            {copied ? (
              <Check className="h-3.5 w-3.5 text-success" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </Button>
          <Button variant="ghost" size="icon" aria-label="Download file" onClick={downloadFile} className="h-7 w-7">
            <Download className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      {/* Code */}
      {showLines ? (
        <div ref={containerRef} className="overflow-auto max-h-[60vh] text-sm flex">
          <div className="select-none text-right pr-3 pl-3 py-4 text-[var(--fg-muted)]/40 font-mono text-xs leading-[1.7] border-r border-[var(--border)] bg-[var(--bg-sidebar)]/50 shrink-0">
            {code.split("\n").map((_, i) => (
              <div key={i} data-line={i + 1} id={`${blockId}-l${i + 1}`}>
                {i + 1}
              </div>
            ))}
          </div>
          <div
            className="flex-1 [&_pre]:!bg-transparent [&_pre]:p-4 [&_pre]:m-0"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        </div>
      ) : (
        <div
          ref={containerRef}
          className="overflow-auto max-h-[60vh] text-sm [&_pre]:!bg-transparent [&_pre]:p-4 [&_pre]:m-0"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      )}
    </div>
  );
}
