# Migration Project — Design

Status: proposed. This is the keystone for app cohesion. Today each screen is an
independent tool: the five analysis screens share one in-session estate, and
Convert hands its file to the Assistant and Advisor, but nothing survives a
reload, no screen knows what another already did, and no workflow carries a
status. A Migration Project is the durable object every screen reads and writes,
so the app becomes one continuous workflow instead of a set of tools behind a
shared sidebar.

## What a Migration Project is

One server-side object representing the estate a user is migrating:

- an **id** and a name
- the **workflow files**, uploaded once and stored, so no screen asks for them again
- a **per-workflow lifecycle status** (assessed, converted, reviewed, deployed)
- the **computed artifacts** already produced per screen (analysis, profile,
  savings inputs/result, readiness, conversion output refs, review decisions)
- **rollups** for the estate dashboard (coverage, auto-convertable %, effort
  hours, savings, workflows by stage)

Everything the four-lens assessment asked for follows from this object: upload
once, a journey with a sense of place, visible progress, and value in one view.

## Design constraints

- **Optional, matching history and AI.** With no database configured, the app
  behaves exactly as it does today — ephemeral, per-visit, no project. The
  project layer is additive: when a backend is present it persists; when it isn't
  the existing in-session stores remain the fallback. This mirrors the existing
  rule that history is optional and AI is opt-in; a default self-host run must
  still work with no external dependencies.
- **Reuse the existing persistence path.** `server/services/history.py` already
  owns the optional Postgres/Lakebase pattern — pool creation, `init_db()` table
  creation, graceful degradation on `psycopg.Error`, backend resolution via
  `resolve_backend()`. The project store uses the same pool and the same
  degradation discipline. No new database technology.
- **Deterministic core is untouched.** The project is a persistence and
  orchestration layer around the existing parse → convert → generate pipeline and
  the analyzer. It changes where files and results are read from, not how
  conversion works. No language model enters any non-advisory path.
- **Files are stored once, by reference.** Workflow files (and extracted `.yxzp`
  contents) are written to a per-project directory — a local temp dir for
  self-host, a Unity Catalog Volume for the Databricks App — and the database row
  holds the metadata and the storage path, not the bytes. Small `.yxmd` bytes may
  be inlined in a first cut, but the volume path is the model so a 300-workflow
  estate scales.

## Data model

Two tables, same pool and `init_db()` discipline as `conversion_history`.

**`migration_project`**
- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `name TEXT NOT NULL`
- `created_at TIMESTAMPTZ DEFAULT NOW()`, `updated_at TIMESTAMPTZ`
- `storage_uri TEXT` — the volume/dir holding this project's files
- `rollups JSONB` — cached estate totals (coverage, auto-convertable %, effort
  hours, savings, counts by stage), recomputed when a workflow's state changes

**`project_workflow`**
- `id UUID PRIMARY KEY`
- `project_id UUID REFERENCES migration_project(id)`
- `file_name TEXT NOT NULL`, `source_path TEXT NOT NULL` (within `storage_uri`)
- `stage TEXT NOT NULL DEFAULT 'uploaded'` — one of `uploaded`, `assessed`,
  `converted`, `reviewed`, `deployed`
- `analysis JSONB`, `savings_inputs JSONB`, `conversion_refs JSONB`,
  `review_decisions JSONB` — the artifacts each screen produces, written as the
  user completes that stage
- `updated_at TIMESTAMPTZ`

The lifecycle is a forward-only ordering for display; a workflow can be
re-converted or re-reviewed, which updates the artifact and timestamp without
moving backward. "Deployed" is set manually by the user (the app does not deploy
customer pipelines), so it is a checkbox, not an inferred state.

## API

New router `server/routers/projects.py`, service `server/services/project.py`.
All endpoints degrade to 404/"projects unavailable" when no backend is
configured, so the client knows to fall back to the in-session stores.

- `POST /api/projects` — create a project; multipart upload of one or more
  Alteryx files (`.yxmd/.yxmc/.yxwz/.yxzp`). Files are materialized once (reusing
  `server/utils/package.materialize_uploads`, which already extracts `.yxzp`
  macros co-located), stored under the project's `storage_uri`, and recorded as
  `project_workflow` rows at stage `uploaded`. Returns the project with its
  workflow list.
- `GET /api/projects` / `GET /api/projects/{id}` — list / fetch, including
  workflows, stages, and rollups.
- `POST /api/projects/{id}/workflows` — add files to an existing project.
- `GET /api/projects/{id}/workflows/{wf_id}/file` — fetch stored bytes, so any
  screen can operate on a project workflow without a re-upload.
- `PATCH /api/projects/{id}/workflows/{wf_id}` — set stage and/or artifact
  (called by the analysis, conversion, and review services on completion);
  triggers a rollup recompute.
- `DELETE /api/projects/{id}` — remove the project and its stored files.

**Existing services gain an optional project reference.** Convert, Analyze,
Profiler, Portfolio, Savings, Readiness, Review, Advisor, Assistant each accept
either an upload (today's behavior) or a `project_id` + `workflow_id`. Given the
latter, they read the stored file instead of requiring an upload, and on success
`PATCH` the workflow's stage and artifact. This is the change that removes
re-uploads across the whole app, not just the analysis cluster.

## Client

One project-scoped store (`frontend/src/stores/project.ts`) hydrated from the
server object, replacing the three disconnected stores (`estate`,
`convert-bridge`, `local-history`) for the project case; those remain as the
no-backend fallback. Two new surfaces read from it:

- **Journey rail** — a thin strip on every screen showing the stages (Assess →
  Business case → Convert → Review → Deploy), the current stage lit, and
  per-stage counts from the rollups. This is the sense-of-place element; it turns
  the sidebar's implied order into a visible one.
- **Estate dashboard as home** — when a project is active, Home leads with the
  rollups (coverage, auto-convertable %, hours and dollars saved to date,
  workflows by stage) and a resumable workflow list, instead of engine stats.
  Each result screen ends with its contribution to those totals.

A workflow picker replaces the bare dropzone on the single-file screens
(Convert, Review, Advisor, Assistant): pick a workflow already in the project, or
add a new one. The dropzone stays for the no-project path.

## Phasing

**Phase 1 — the object and the spine.** `migration_project` + `project_workflow`
tables, the project service and router, `POST /api/projects` storing files once,
and the client project store. Journey rail reading `uploaded`/`assessed`/
`converted` counts. Convert and the analysis screens read project files instead
of re-uploading. This alone removes the re-upload complaint and gives a sense of
place.

**Phase 2 — full lifecycle and value.** Wire Review, Advisor, Assistant, Batch to
project files; set `reviewed`/`deployed`; estate dashboard as home; per-screen
completion signals ("+1 converted, +6 hours saved toward the estate").

**Phase 3 — enterprise finishers.** Actionable Portfolio waves ("Convert Wave 1"
→ Batch scoped to that wave), a shareable/resumable project link, and persisted
in-progress Review/Batch/Assistant state.

## What this builds on

This session already shipped the first cohesion layer: an in-session shared
estate across the five analysis screens, a Convert → Assistant/Advisor file
handoff, next-step callouts on the hubs, and hub consolidation. Those are the
right foundation. The Migration Project makes that cohesion durable (survives a
reload), extends it to the Convert and Review side, and adds the lifecycle and
rollups that give the user a journey and a scoreboard. The in-session stores
become the no-backend fallback rather than being replaced.

## Testing

- Project service against the same pool pattern history uses; table creation,
  CRUD, stage transitions, rollup recompute, and graceful degradation when no
  backend is configured (returns the "unavailable" path, never 500).
- Each existing service's new project-read path: given `project_id` +
  `workflow_id`, it reads the stored file and produces the same result as the
  upload path (parametrized against the current tests).
- A `.yxzp`-with-macro project: stored once, read by Analyze and Convert without
  re-upload, macro expanded on both (guards the fix from the macro PR against
  regression through the project path).
- Frontend: journey rail counts, workflow picker, dashboard rollups, and the
  no-project fallback still working with no backend.
