# Alteryx-to-Databricks Migration Accelerator — UX, Usability, and Design Assessment

**Assessment date:** 2026-08-05  
**Scope:** React application information architecture, onboarding, primary workflows, interaction design, responsive behavior, accessibility, data communication, AI trust, visual language, error/recovery states, and user confidence.  
**Method:** Source review plus rendered inspection of the home, conversion, assistant, and mobile home screens at desktop and 390 × 844 viewports. No product code was changed.

## Action taken (added 2026-08-05)

Correctness and trust items were fixed. Items that redesign the product model are
recorded as decisions for the owner rather than actioned unilaterally.

| ID | Outcome |
|---|---|
| **UX-02** | **Fixed.** Cancel really cancels: `POST /api/convert/batch/{id}/cancel` + `cancel_job()`. The button says "Stop conversion" and states the honest boundary (the in-flight file finishes; the rest are skipped). A test caught that `BatchStatusResponse` didn't allow `"cancelled"` — polling after a cancel would have 500'd. |
| **UX-03** | **Fixed.** "Code is ready for Databricks" → "Python syntax passed … runtime behavior, dependencies, permissions, SQL and semantic equivalence are NOT verified", plus a 5-step validation ladder kept next to the result. |
| **UX-04 / UX-18** | **Fixed.** Coverage and confidence now carry definitions directly under the value, so a heuristic doesn't read as a measurement. |
| **UX-14** | **Fixed.** `prefers-reduced-motion` was ignored across five animated components. Global CSS rule + a JS check for the `requestAnimationFrame` count-up. |
| **UX-17** | **Fixed.** Conversion and batch progress announce via `role="status"` + `aria-live`. |
| UX-01, UX-05, UX-06, UX-07 | **Owner decision.** A Migration Workspace, renamed navigation, a stratified results page and a format-comparison table are product-model changes, not defects. The analysis is sound; the scope needs a product call. |
| UX-08, UX-09 | Open. Run-configuration summary and carrying the file between Analyze → Convert both need a session/project model to exist first (related to UX-01). |
| UX-10, UX-11, UX-12 | Open. AI identity surfacing needs a `/api/whoami`; the disabled-assistant copy and the two history storage models are copy/IA decisions. |
| UX-13, UX-15, UX-16, UX-19..UX-23 | Open. Mobile dialog focus, semantic-color consistency, mobile hierarchy, home-page content, terminology and settings feedback — all real, all lower risk than the above. |

Also fixed alongside these, from the codebase audit: the production bundle shipped
~1.9 MB of unused syntax grammars — **dist went 11.6 MB → 2.6 MB (-78%)**, which
improves App cold start — and two WebSocket reconnect races (uncleared retry timers,
stale sockets nulling an active connection).

## Executive assessment

The interface is visually credible and more polished than most migration utilities. It has consistent spacing, clear typography, restrained color, useful empty/loading/error states, responsive card stacking, dark mode, descriptive buttons, and a strong deploy-readiness concept. The single-conversion screen is especially approachable: upload, confirm settings, convert.

The primary usability problem is the product model. The app exposes 13 destinations grouped as separate tools—Analyze, Portfolio, Tools, Convert, Batch, History, Validate, Review, Advisor, Assistant, Settings, About, and Home—while the user's real task is one continuous journey: understand a workflow, convert it, resolve blockers, validate equivalence, and deploy. Users must repeatedly upload the same file, infer the difference between overlapping pages, and carry context manually between them. The UI behaves like a toolbox; the target users need a migration workspace.

The second major issue is trust calibration. “Syntax Valid” currently says code is “ready for Databricks,” although the same screen later explains that it is only Python syntax validation. Coverage, confidence, best format, deploy readiness, and tool support are prominent but lack concise, adjacent definitions and provenance. The assistant appropriately says it is advisory, but does not identify the signed-in user, execution identity, configured model, or source facts behind an answer.

### UX scorecard

| Dimension | Rating | Assessment |
|---|---:|---|
| Visual polish | 8/10 | Clean, consistent, professional, good density on simple screens. |
| Learnability | 6/10 | Helpful copy, but too many peer destinations and technical terms. |
| Task efficiency | 5/10 | Repeated uploads and fragmented workflow create unnecessary effort. |
| Feedback/recovery | 7/10 | Good loading and retry patterns; some actions are misleading or incomplete. |
| Information hierarchy | 6/10 | Strong page headers, but results pages duplicate metrics and bury next actions. |
| Accessibility | 5/10 | Some labels and responsive behavior are good; focus, motion, semantic color, and announcements need work. |
| Mobile usability | 7/10 | Home stacks cleanly; dense result pages and header actions need dedicated treatment. |
| Trust/transparency | 5/10 | Advisory boundary and warnings are good; validation and AI identity claims need correction. |

## Product direction

**Audience:** migration engineers, solution architects, and technical reviewers deciding whether an Alteryx workflow can move to Databricks and what work remains.  
**Primary task:** take a workflow or portfolio from assessment through reviewed, downloadable migration artifacts with clear evidence and next steps.  
**Recommended genre:** an **analytic migration workspace** with a stratified overview → blockers → generated artifacts → review/validation structure. Portfolio is a parallel estate-level analytic view, not a peer step in every single-workflow journey.

The design should optimize for three user questions:

1. Can this workflow migrate, and what blocks it?
2. Which generated target should I use, and what must I review?
3. What is the next concrete action to reach deployable status?

## What works well

- The visual system is restrained and professional; the rendered desktop and mobile home screens are coherent.
- Navigation grouping into Assess / Migrate / Validate / Assist is better than a flat menu.
- The home hero gives two clear entry points and includes first-visit guidance.
- The conversion upload screen is low-friction and shows the active catalog/schema.
- File drop, loading skeletons, inline errors, retries, downloads, and reset actions are consistently present.
- Responsive home cards stack into a comfortable single-column mobile layout.
- Conversion results lead with a three-tier deploy-status banner and distinguish automated work from manual review.
- Warning categorization converts raw technical warnings into more usable groups.
- The assistant visibly states that it is advisory and cannot alter generated code.
- Dark mode, route-level error boundaries, lazy loading, and stale-chunk retry are thoughtful product-quality details.
- Settings previews help users understand otherwise abstract generator options.

## Prioritized findings

### Critical usability and trust issues

#### UX-01 — The app is a toolbox, not a continuous migration workflow

**Evidence:** `frontend/src/components/layout/sidebar.tsx:40-80` exposes 13 destinations. Analyze, Convert, Review, Validate, Advisor, and Assistant each begin as separate workflows. Analyze only passes a workflow name to Convert, which then asks for the file again (`frontend/src/routes/convert.tsx:89-95`). Review and Assistant also require uploads.

**User impact:** People lose context, repeat work, and must decide which internal capability to invoke next. A migration may span several browser pages with no persistent project state.

**Recommendation:** Introduce a **Migration Workspace** keyed by workflow/project:

- Overview: readiness, best target, blockers, last run, recommended next action.
- Generated artifacts: five formats with downloads.
- Review: node decisions and edits.
- Validation: syntax plus semantic verification status.
- Advisor/Assistant: contextual tabs using the same parsed DAG and artifacts.
- Activity: prior runs and reports.

Keep Portfolio as an estate-level entry. Move Tools and About under Help/Reference. Settings can remain global but should also be editable per run.

#### UX-02 — “Cancel” does not cancel batch conversion

**Evidence:** `frontend/src/routes/convert-batch.tsx:35-41` only disconnects the WebSocket, clears local state, and shows “Batch conversion cancelled.” It does not call a backend cancellation endpoint; server work continues.

**User impact:** Misleading feedback, wasted compute, and surprise when work or artifacts continue to exist.

**Recommendation:** Either implement true backend cancellation and use “Cancel batch,” or rename the current action to “Stop watching” with an explicit “conversion continues in the background” message and a route back to the job.

#### UX-03 — Syntax validation overclaims deployment readiness

**Evidence:** `frontend/src/routes/validate.tsx:95-98` says, “No syntax errors found. Code is ready for Databricks.” The tips at `:140-143` admit SQL is unsupported and full validation requires execution against data.

**User impact:** This can create false confidence in generated code and is especially risky for a migration accelerator.

**Recommendation:** Change the success message to: “Python syntax passed. Runtime behavior, dependencies, permissions, SQL, and semantic equivalence are not verified.” Present a validation ladder:

1. Syntax checked
2. Generator warnings resolved
3. Semantic verification completed
4. Databricks runtime smoke test completed
5. Deployment configuration validated

Only use “ready to deploy” when all required gates pass.

#### UX-04 — Primary metrics lack definitions, provenance, and freshness

**Evidence:** Home cards show Tool Coverage, Recognized Tools, Expression Functions, and Output Formats (`frontend/src/routes/index.tsx:153-177`) without “as of,” source/version, numerator/denominator, or explanation. Results prominently display coverage, confidence, and best format with limited adjacent explanation (`frontend/src/components/convert/conversion-results.tsx:234-338`).

**User impact:** Users cannot judge whether 75% tool coverage applies to their workflow, the global registry, or execution parity. “Confidence 82/100” can look more scientifically precise than its heuristic basis.

**Recommendation:** Add concise definitions and provenance:

- “Registry coverage: 113 of 151 recognized Alteryx tools have deterministic or templated converters.”
- “Workflow coverage: percentage of nodes with a generated implementation in this format; not semantic correctness.”
- “Confidence: heuristic based on mapping method, warnings, and graph context.”
- Show converter version/build and analysis time beside results.

Use tooltips or a “How scoring works” drawer, but keep the essential limitation adjacent to the number.

### High priority

#### UX-05 — Navigation labels overlap conceptually

**Evidence:** Analyze, Portfolio, Validate, Review, and Advisor are peers under three groups. “Validate” can mean syntax, semantic equivalence, or deployment validation; “Review” could mean the whole workflow; “Advisor” does not say cost/performance.

**Recommendation:** Rename and consolidate:

| Current | Recommended |
|---|---|
| Analyze | Readiness assessment |
| Portfolio | Migration portfolio |
| Validate | Syntax check, nested under workspace validation |
| Review | Code review, nested under a workflow |
| Advisor | Cost & performance |
| Tools | Support reference |
| Assistant | Migration assistant |

Use step/status navigation inside a workspace instead of exposing every capability globally.

#### UX-06 — The conversion results page overloads users before telling them what to do

**Evidence:** It presents a deploy banner, three count chips, best-format callout, download action, five metric cards, workflow graph, warning groups, five format tabs, per-format metrics, file tabs, and code. Several values repeat coverage/confidence and counts.

**User impact:** Reviewers must scan a long page to discover the highest-impact blockers and next action. The detailed code dominates even when the user first needs a decision summary.

**Recommendation:** Use a stratified structure:

1. **Decision header:** status, best target, one-sentence rationale, primary next action.
2. **Blockers:** unsupported nodes and manual-review items, sorted by severity and workflow position.
3. **Plan:** “Resolve 3 local paths → review 1 expression → run verification.”
4. **Artifacts:** format comparison table and downloads.
5. **Technical detail:** graph, metrics, code, and raw warnings behind tabs/disclosure.

Remove duplicate metric cards when the same information already appears in the status summary.

#### UX-07 — “Best format” needs an explicit comparison, not only a badge

**Evidence:** Results identify a best format and confidence, while all five outputs remain available. Users are not shown why the winner is better or what is sacrificed.

**Recommendation:** Add a compact comparison table:

| Format | Coverage | Manual-review nodes | Failed checks | Best for | Recommendation |

The title should state the conclusion: “PySpark has the highest coverage; SDP needs two additional manual rewrites.” Let users compare without switching five tabs.

#### UX-08 — Hidden global settings make conversion outcomes surprising

**Evidence:** Convert summarizes only catalog/schema and comments (`frontend/src/routes/convert.tsx:109-116`), while six generator options can be persisted globally in Settings. Batch shows only catalog/schema.

**Recommendation:** Before execution, show a collapsible **Run configuration** summary containing every active option and offer “Edit for this run.” Separate global defaults from per-run configuration. Display configuration alongside saved history so results are reproducible.

#### UX-09 — Re-uploading after analysis breaks momentum

**Evidence:** Analyze can navigate users to Convert, but only passes the workflow name; Convert tells them to upload the same `.yxmd` again.

**Recommendation:** Retain the selected `File` in session memory for same-tab transitions, or persist the parsed DAG/server-side project with a short-lived opaque ID. The CTA should be “Convert this workflow,” not “go to Convert and upload again.” Provide an explicit privacy/retention explanation.

#### UX-10 — AI trust and identity are incomplete

**Evidence:** The assistant clearly discloses its advisory-only boundary, which is good. It does not show the signed-in user, whether calls run as the App service principal, the configured model/endpoint label, the facts used for an answer, or a per-answer verification reminder. No `/api/whoami` surface exists.

**Recommendation:** Show:

- Signed-in identity and truthful execution identity.
- “Uses converter facts from workflow X, generated at time Y.”
- Model/endpoint display name when enabled.
- Expandable grounding facts or cited node/warning references per answer.
- Persistent “AI-generated suggestion—verify before implementation” near each answer.
- Clear empty, ambiguous, timeout, and retry states.

This assistant is not a Genie SQL surface, so generated SQL is not required; source facts and node references are the appropriate equivalent.

#### UX-11 — The disabled assistant state is aimed at operators, not end users

**Evidence:** The page tells users to set `A2D_FMAPI_ENDPOINT` and `A2D_FMAPI_TOKEN`. Most Databricks App users cannot do this.

**Recommendation:** Separate audiences: “Assistant is not enabled for this deployment. Ask your app administrator to configure it.” Put environment-variable instructions behind an “Administrator setup” disclosure and offer the deterministic Suggestions report/other available workflow as the user-facing alternative.

#### UX-12 — History presents two storage models without a clear mental model

**Evidence:** History merges server/Lakebase and browser-local entries and tracks a `source` distinction. Users may see duplicates, different retention, or results that exist only on one device.

**Recommendation:** Prefer one durable, user-owned history. Until then, label sections “Workspace history” and “This browser,” explain retention/privacy, deduplicate matching conversions, and clearly state which records survive browser clearing or App restart.

### Accessibility and responsive design

#### UX-13 — Mobile navigation lacks dialog/focus behavior

**Evidence:** `frontend/src/components/layout/sidebar.tsx:91-115` toggles an overlay and off-canvas aside, but does not trap focus, close on Escape, restore focus, or mark background content inert. The aside has no dialog/navigation state relationship beyond `aria-expanded` on the button.

**Recommendation:** Implement a proper accessible sheet/drawer: `aria-controls`, Escape dismissal, initial focus, focus trap, background `inert`, focus restoration, and scroll locking. Ensure route changes announce the new page title.

#### UX-14 — Motion does not respect reduced-motion preferences

**Evidence:** Page transitions, home entrance animations, auto-scroll, flashing code lines, spinners, and pulsing text are used without a visible `prefers-reduced-motion` path.

**Recommendation:** Add a global reduced-motion media query and use Motion's reduced-motion support. Replace smooth scroll/flash with instant focus and a static outline for users who request reduced motion.

#### UX-15 — Semantic color is inconsistent and partly hardcoded

**Evidence:** Raw Tailwind red/green/yellow/blue classes appear throughout results and validation; graph components hardcode hex values (`frontend/src/components/review/review-graph.tsx:27-35`, `frontend/src/components/convert/workflow-graph.tsx:22-24`).

**Recommendation:** Use the shared semantic tokens for success/warning/destructive/info across HTML and graph nodes. Always pair color with icon/text/pattern. Test contrast in light and dark themes and for common color-vision deficiencies.

#### UX-16 — Complex pages need mobile-specific hierarchy, not only wrapping

**Evidence:** The mobile home layout is strong. However, `PageHeader` is a non-wrapping `flex` row (`frontend/src/components/layout/page-header.tsx:11-18`), while Analyze and Batch can render two or three header actions. Results contain five format/file tabs, graphs, code, and wide tables.

**Recommendation:** Stack header actions below titles on small screens, turn tab strips into scrollable labeled controls or selects, offer a “Summary / Blockers / Code” mobile view, and provide explicit horizontal-scroll affordances for tables/code. Test 320 px, 390 px, tablet, and 200% zoom.

#### UX-17 — Async feedback should be announced, not only shown visually

**Evidence:** Spinners, toast messages, batch progress, conversion completion, and validation results are primarily visual. Toast/status containers should use appropriate live-region semantics without over-announcing frequent progress.

**Recommendation:** Use `aria-live="polite"` for completion/status summaries, `role="alert"` for blocking failures, named progress elements with current/total values, and move focus to the results heading after a user-triggered operation.

#### UX-18 — Small muted text is overused for consequential information

**Evidence:** Settings descriptions/previews, conversion configuration, warnings, build information, and explanatory copy frequently use 10–12 px muted text. This looks tidy but weakens readability and makes critical caveats easy to miss.

**Recommendation:** Reserve 10 px for nonessential metadata. Use at least 14 px for instructions, limitations, and status explanations; verify WCAG contrast for muted text in both themes.

### Information design and visual refinement

#### UX-19 — Home capability cards are product telemetry, not user decisions

**Evidence:** The rendered home dedicates a full row to registry counts. These do not help a returning user continue a migration or decide what to do next.

**Recommendation:** For new users, show a three-step journey. For returning users, prioritize active/recent migrations, unresolved blockers, and “continue review.” Move engine capability statistics to About/Support Reference, or reduce them to a small trust footnote with version/freshness.

#### UX-20 — Home repeats onboarding and primary actions

**Evidence:** Hero CTAs, four quick-action cards, and a “New here? Start with analysis” panel repeat Analyze and Convert within one viewport.

**Recommendation:** Keep one dominant new-user CTA (“Assess workflows”) and one secondary (“Open migration portfolio”). Replace repeated guidance with a concise three-step diagram or recent-work panel.

#### UX-21 — The product language is accurate but unnecessarily technical

**Evidence:** The home Convert card lists all five technologies in one sentence; page copy uses IR, DAB, DDL, SDP, coverage, confidence, deterministic, mapping, and expression-engine language.

**Recommendation:** Lead with outcomes, then reveal implementation terms:

- “Generate five Databricks target options” with a details link.
- “Deployment bundle” before “DAB.”
- “Catalog table setup” before “DDL.”
- Explain “best format” as “recommended target for this workflow.”

Maintain exact platform terminology in technical detail and downloads.

#### UX-22 — Empty vertical space makes simple pages feel unfinished on desktop

**Evidence:** The rendered Convert page uses only the upper third of a 1440 × 900 view after the upload/control row. The Assistant disabled state similarly leaves a large blank canvas.

**Recommendation:** Use the space for useful, low-noise context: accepted input and privacy, what will be generated, active run configuration, recent workflow, sample file, or next steps. Do not fill it with decorative dashboards.

#### UX-23 — Settings autosave feedback is not tied to the changed control

**Evidence:** A static “All settings are saved automatically” message is always present. There is no per-change confirmation, undo, dirty state, or clear indication of whether defaults affect existing results.

**Recommendation:** Show a brief “Saved” status after changes, provide undo/reset confirmation, distinguish global defaults from current-run overrides, and explain that past artifacts are unchanged.

#### UX-24 — Error copy sometimes targets developers rather than deployed users

**Evidence:** Home API failure instructs users to run `make serve` or Uvicorn (`frontend/src/routes/index.tsx:141-145`). This is useful locally but inappropriate inside a managed Databricks App.

**Recommendation:** Detect development mode. Production copy should say the service is unavailable, preserve user inputs, offer retry, and provide a support/request ID. Put developer commands only in development builds.

## Recommended information architecture

```text
Home
├── New migration
├── Active/recent migrations
└── Migration portfolio

Migration workspace: <workflow>
├── Overview            status, recommendation, next action
├── Blockers & review   unsupported nodes, warnings, reviewer decisions
├── Generated targets   five-format comparison, files, downloads
├── Validation          syntax, semantic verification, Databricks checks
├── Cost & performance  cluster recommendation and hints
├── Assistant           grounded advice for this workflow
└── Activity            runs, reports, configuration, audit trail

Portfolio
├── Estate overview
├── Dependencies
├── Migration waves
└── Workflow drilldown → Migration workspace

Reference
├── Tool support
├── Documentation
└── About/version

Settings
```

## Recommended component plan

This repository is a custom React/FastAPI App rather than AppKit, so use the existing local primitives or equivalent published AppKit primitives if the UI is later migrated.

| Element | Component approach | Required states |
|---|---|---|
| Workspace status header | `Card` + `Badge` + primary `Button`; semantic tokens only | loading, partial, stale, failed |
| Next-action plan | ordered checklist with owner/status and direct links | empty = ready; blocked explanation |
| Format comparison | responsive `Table`, sortable by coverage/review count | loading, empty, failed format, partial |
| Blocker list | grouped `Card`/collapsible sections, severity icon + text | none, partial, error |
| KPI/metrics | composed `Card`; unit, definition, source/version, freshness | skeleton, unavailable, stale |
| Workflow graph | graph + synchronized accessible table/list alternative | empty, large graph, keyboard selection |
| AI identity/trust | identity `Badge`, execution disclosure, source-facts disclosure | disabled, loading, timeout, ambiguous, error |
| Notifications | inline `Alert` for persistent state; toast only for transient confirmation | live-region semantics |
| Mobile navigation | accessible sheet/drawer | focus trap, Escape, restore focus |

## Suggested delivery sequence

### Phase 1 — Correct trust and misleading behavior

1. Correct Validate success language.
2. Fix or rename Batch Cancel.
3. Add metric definitions and AI execution/grounding disclosure.
4. Split production errors from developer instructions.
5. Show all run settings before conversion.

### Phase 2 — Reduce workflow friction

1. Preserve uploaded workflow/context from Analyze → Convert → Review.
2. Add a workflow workspace shell with Overview, Blockers, Artifacts, and Validation.
3. Consolidate navigation and rename ambiguous tools.
4. Add a format comparison and recommended next-action plan.

### Phase 3 — Accessibility and responsive hardening

1. Accessible mobile drawer and focus management.
2. Reduced-motion support and semantic live regions.
3. Tokenize colors and test contrast/color vision.
4. Mobile-specific result layout and 200% zoom testing.
5. Automated axe and keyboard journey tests.

### Phase 4 — Visual and content refinement

1. Replace repeated home onboarding with recent/active work.
2. Move capability telemetry to reference/about.
3. Simplify technical labels and add contextual explanations.
4. Use desktop whitespace for useful configuration/privacy/next-step context.

## Usability test plan

Test with at least five migration engineers and three solution architects. Give no product tour.

1. Assess three workflows and identify the least migration-ready one.
2. Convert one workflow and explain why the recommended format was selected.
3. Find every blocker that prevents deployment and state the next action.
4. Review one generated node, edit it, and export the reviewed artifact.
5. Determine exactly what “syntax valid,” “coverage,” and “confidence” guarantee.
6. Start and cancel a batch; verify the user's mental model matches actual server behavior.
7. Ask the assistant a question and identify who executed the call and what facts grounded the response.
8. Complete the core flow at 390 px and with keyboard only.

Measure task success, time, repeated uploads, navigation reversals, interpretation errors, and confidence calibration—not merely satisfaction.

## Assessment limitations

- Rendered inspection covered representative empty/disabled states but not authenticated production identity, populated conversion/analysis/review data, or a live batch.
- No screen reader or automated axe run was performed; accessibility findings combine source inspection and keyboard/semantic heuristics.
- The Databricks App Design skill influenced the required treatment of data provenance, loading/empty/error/partial states, semantic color, and AI identity/trust. AppKit components were not prescribed because this application currently uses its own React primitives.

## Definition of “user-friendly enough to ship”

The UI is ready for broad use when a new user can move from assessment to reviewed artifacts without re-uploading, can correctly explain every readiness metric and validation limitation, can reliably cancel or resume work, receives one clear next action at each stage, can identify AI execution and grounding, and can complete the critical journey on mobile and keyboard without losing context.
