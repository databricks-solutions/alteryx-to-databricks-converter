import { createHighlighterCore, type HighlighterCore } from "shiki/core";
import { createOnigurumaEngine } from "shiki/engine/oniguruma";

/**
 * Syntax highlighter loaded with ONLY the languages the UI can render.
 *
 * The `shiki` bundled entry point ships every grammar it knows about regardless of
 * what `langs` asks for, which put ~1.9 MB of emacs-lisp, C++ and WASM grammars
 * into the production build for a UI that highlights Python, SQL and JSON (see the
 * allowlist in components/shared/code-block.tsx). The core entry point imports only
 * what is listed here.
 *
 * Adding a language means importing its grammar here AND adding it to
 * ALLOWED_LANGUAGES in code-block.tsx — the two are deliberately explicit so an
 * unused grammar can't creep back into the bundle.
 */
let highlighterPromise: Promise<HighlighterCore> | null = null;

export function getHighlighter(): Promise<HighlighterCore> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighterCore({
      themes: [
        import("shiki/themes/github-dark.mjs"),
        import("shiki/themes/github-light.mjs"),
      ],
      langs: [
        import("shiki/langs/python.mjs"),
        import("shiki/langs/sql.mjs"),
        import("shiki/langs/json.mjs"),
      ],
      engine: createOnigurumaEngine(import("shiki/wasm")),
    });
  }
  return highlighterPromise;
}
