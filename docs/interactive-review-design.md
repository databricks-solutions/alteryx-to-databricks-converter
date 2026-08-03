# Interactive Review Workspace — Design

Q3 #4. Lets a reviewer see the Alteryx canvas beside the generated Databricks
code and accept or edit each node's conversion before adopting it.

## Backend (implemented)

The reviewable model is built server-side and served as JSON; reviewer
decisions are applied against that model.

- **`a2d.review.models`**
  - `ReviewNode` — one node: canvas metadata (tool type, annotation, position),
    the generated code cell, `status`, `confidence`, `warnings`,
    `conversion_method`, plus mutable reviewer state (`decision` ∈
    pending/accepted/edited/rejected, and an `edited_code` override).
    `effective_code` returns the edit if present else the generated code.
  - `ReviewStatus` — how the auto-conversion turned out:
    `auto_accepted` (high confidence, no warnings), `needs_review` (low
    confidence or warnings), `cannot_convert` (an `UnsupportedNode`). Computed
    by `node_review_status`.
  - `ReviewSession` — nodes + edges + progress (`needs_review_count`,
    `resolved_count`, `is_complete` = every needs-review/cannot-convert node has
    a decision). `accept`/`reject`/`edit` mutate node state.
- **`a2d.review.builder.build_review_session(dag, name, output_format, config)`**
  Runs the chosen generator once and splits its output on the per-node
  `# Step <id>:` / `-- Step <id>` markers the generators already emit, matching
  each cell to its node. This guarantees the code shown per node is exactly what
  the generator produces — no second code path to drift. Generator warnings that
  mention `node <id>` are attached to that node.
- **`POST /api/review`** (`server/routers/review.py`) — multipart upload of one
  `.yxmd`/`.yxmc` + optional `output_format` form field (default `pyspark`).
  Returns the `ReviewSession.to_dict()` shape:
  ```json
  {
    "workflow_name": "...", "output_format": "pyspark",
    "summary": {"total": N, "needs_review": N, "resolved": N, "complete": false},
    "nodes": [{"node_id", "tool_type", "position_x", "position_y", "status",
               "confidence", "generated_code", "warnings", "decision", ...}],
    "edges": [{"source_id", "target_id", "origin_anchor", "destination_anchor"}]
  }
  ```

## Frontend (implemented)

The `ReviewPage` route (`frontend/src/routes/review.tsx`, nav item **Review**)
is a thin rendering layer over the verified `/api/review`:

1. Uploads a workflow via `useReview` (`hooks/use-review.ts` → `api.review`) and
   renders two synced panes:
   - **Canvas** (`components/review/review-graph.tsx`, a react-flow + dagre LR
     layout adapted from `workflow-graph.tsx`) laid out from `nodes[]` + `edges`,
     each node coloured by `status` (green/amber/red) — a resolved decision
     recolours the node green, a reject red, so the canvas doubles as a progress
     view.
   - **Code** pane showing the selected node's `generated_code` in the existing
     Shiki-highlighted `CodeBlock`, with an inline textarea editor for edits.
2. Selecting a node cross-highlights canvas ↔ code (selected node gets a ring +
   fill). Per-node **Accept** / **Edit** / **Reject** controls update local
   review state; a progress bar reads resolved / needs-review counts.
3. **Export** concatenates each node's effective code (reviewer edit if any) in
   the topological node order the builder emits, skipping rejected nodes, and
   downloads the final artifact.

Reviewer decisions are held client-side (a `node_id → {decision, edited_code}`
overlay) against the server model; the backend model, status logic,
cell-splitting and endpoint are fully covered by backend tests, and the UI was
verified end-to-end against a running server (upload → panes → select → accept →
export, no console errors).
