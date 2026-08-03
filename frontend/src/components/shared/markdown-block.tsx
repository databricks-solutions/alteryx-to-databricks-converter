import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/cn";

interface MarkdownBlockProps {
  content: string;
  className?: string;
}

/**
 * Renders assistant/report Markdown with the app's typography.
 *
 * Tailwind classes are applied per element rather than via a prose plugin,
 * matching how the rest of the app styles text.
 */
export function MarkdownBlock({ content, className }: MarkdownBlockProps) {
  return (
    <div className={cn("text-sm leading-relaxed text-[var(--fg)] space-y-2", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          h1: ({ children }) => <h1 className="text-base font-semibold mt-3 mb-1">{children}</h1>,
          h2: ({ children }) => <h2 className="text-sm font-semibold mt-3 mb-1">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold mt-2 mb-1">{children}</h3>,
          ul: ({ children }) => <ul className="list-disc pl-5 space-y-1 mb-2">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1 mb-2">{children}</ol>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--ring)] underline"
            >
              {children}
            </a>
          ),
          code: ({ className: codeClass, children }) => {
            // Fenced blocks carry a language- class; inline code does not.
            const isBlock = Boolean(codeClass);
            if (isBlock) {
              return (
                <code className="block overflow-x-auto rounded-lg bg-[var(--bg-sidebar)] p-3 font-mono text-xs">
                  {children}
                </code>
              );
            }
            return (
              <code className="rounded bg-[var(--bg-sidebar)] px-1 py-0.5 font-mono text-xs">
                {children}
              </code>
            );
          },
          pre: ({ children }) => <pre className="mb-2">{children}</pre>,
          table: ({ children }) => (
            <div className="overflow-x-auto mb-2">
              <table className="w-full text-xs border-collapse">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-[var(--border)] px-2 py-1 text-left font-semibold">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-[var(--border)] px-2 py-1">{children}</td>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-[var(--border)] pl-3 text-[var(--fg-muted)]">
              {children}
            </blockquote>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
