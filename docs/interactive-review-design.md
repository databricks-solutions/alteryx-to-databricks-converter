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

## Frontend (integration plan)

The repo's React frontend has no unit-test harness, so the frontend layer is
specified here rather than built blind. A `ReviewPage` route would:

1. Upload a workflow to `POST /api/review` and render two synced panes:
   - **Canvas** (reuse `components/convert/workflow-graph.tsx`) laid out from
     `nodes[].position_x/y` + `edges`, each node coloured by `status`
     (green/amber/red).
   - **Code** pane showing the selected node's `generated_code` in the existing
     Shiki-highlighted viewer, editable for a `needs_review`/`cannot_convert`
     node.
2. Selecting a node cross-highlights canvas ↔ code. Per-node **Accept** / **Edit**
   / **Reject** controls update local review state; a progress bar reads
   `summary.needs_review`/`resolved`.
3. **Export** concatenates each node's `effective_code` (edits applied) in
   topological order into the final artifact.

Because the model, status logic, cell-splitting and endpoint are fully covered
by backend tests, the frontend is a thin rendering layer over a verified API —
the same split used for the Designer round-trip (offline validator tested; live
UI layer separate).
