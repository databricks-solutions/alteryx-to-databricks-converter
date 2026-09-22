"""The migration-readiness question bank — static, Alteryx→Databricks-centric.

This is a **self-assessment** survey answered by a human, distinct from the
automated file-based signal in :mod:`a2d.analyzer.readiness` (which scores parsed
workflows). Everything here is deterministic data: each option carries a 0-100
score and, when the option signals a gap, a concrete tip that names the Databricks
construct or a2d feature to reach for.
"""

from __future__ import annotations

from dataclasses import dataclass

# Dimension ids → human labels. The four areas confirmed for scope.
DIMENSIONS: dict[str, str] = {
    "estate": "Estate & workflow profile",
    "people": "People & skills",
    "platform": "Platform & data landscape",
    "governance": "Governance & sponsorship",
}


@dataclass(frozen=True)
class Option:
    """One selectable answer for a question."""

    value: str
    label: str
    score: float  # 0-100 readiness contribution
    tip: str | None = None  # shown when this option is chosen and signals a gap


@dataclass(frozen=True)
class Question:
    """A single-choice question in one dimension."""

    id: str
    dimension: str
    prompt: str
    options: list[Option]
    weight: float = 1.0

    def option(self, value: str) -> Option | None:
        for opt in self.options:
            if opt.value == value:
                return opt
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dimension": self.dimension,
            "prompt": self.prompt,
            "weight": self.weight,
            "options": [{"value": o.value, "label": o.label, "score": o.score, "tip": o.tip} for o in self.options],
        }


# ── The bank ──────────────────────────────────────────────────────────────
# Kept intentionally compact (4-5 questions per dimension). Scores: a "clean"
# answer sits high (85-95), a mixed one mid (55-65), a gap low (25-45). Tips hang
# off the gap options.

QUESTION_BANK: list[Question] = [
    # ── Estate & workflow profile (prefillable from `a2d assess`) ──
    Question(
        "estate_size",
        "estate",
        "How many Alteryx workflows are in scope for migration?",
        [
            Option("small", "1–10", 90),
            Option("medium", "11–50", 70),
            Option(
                "large",
                "51–200",
                45,
                tip="Large estate — sequence it with `a2d portfolio` waves and migrate high-value, high-coverage workflows first.",
            ),
            Option(
                "xlarge",
                ">200",
                25,
                tip="A very large estate needs a program, not a project: profile it with the Profiler, dedupe shared sub-flows, and stage by wave.",
            ),
        ],
    ),
    Question(
        "macros",
        "estate",
        "How much do your workflows rely on custom or shared macros (.yxmc)?",
        [
            Option("none", "No macros", 90),
            Option(
                "few",
                "A few standard macros",
                65,
                tip="Standard macros inline cleanly — enable `--expand-macros` so the converter folds them into the pipeline.",
            ),
            Option(
                "many",
                "Many / iterative macros",
                30,
                tip="Iterative macros have no 1:1 equivalent — plan to rewrite them as Lakeflow Jobs; inventory them early.",
            ),
        ],
    ),
    Question(
        "advanced_tools",
        "estate",
        "Do workflows use spatial, predictive/ML, R, or custom Python / Run-Command tools?",
        [
            Option("none", "None — mostly prep/join/transform", 90),
            Option(
                "some",
                "Some spatial or reporting tools",
                60,
                tip="Spatial maps to Sedona/H3 and reporting to AI/BI dashboards — the converter emits templates but expect manual finishing.",
            ),
            Option(
                "heavy",
                "Heavy ML / R / custom code",
                30,
                tip="Predictive and R/Python tools are a rebuild on MLflow + Spark ML — defer this tail and migrate the deterministic core first.",
            ),
        ],
    ),
    Question(
        "scheduling",
        "estate",
        "How are workflows scheduled or orchestrated today?",
        [
            Option("manual", "Run manually / ad-hoc", 80),
            Option(
                "server",
                "Alteryx Scheduler / Server gallery",
                60,
                tip="Recreate schedules as Lakeflow Jobs and map Server gallery apps to parameterized jobs.",
            ),
            Option(
                "external",
                "External orchestrator (Airflow, Control-M, …)",
                55,
                tip="Keep the orchestrator but repoint tasks at Databricks Jobs, or migrate triggers into Lakeflow.",
            ),
        ],
    ),
    Question(
        "documentation",
        "estate",
        "How well documented is the business logic in your workflows?",
        [
            Option("good", "Well documented", 90),
            Option(
                "partial",
                "Partially documented",
                60,
                tip="Capture intent for the undocumented parts before converting — it is the cheapest risk reduction you can do.",
            ),
            Option(
                "tribal",
                "Tribal knowledge only",
                30,
                tip="Undocumented logic is the top migration risk — lock behavior with `a2d verify` against golden outputs exported from Alteryx.",
            ),
        ],
    ),
    # ── People & skills ──
    Question(
        "spark_sql",
        "people",
        "How fluent is the team in PySpark / Spark SQL?",
        [
            Option("strong", "Strong", 90),
            Option(
                "some",
                "Some exposure",
                60,
                tip="Pair converts with Databricks Academy paths; start from the SQL output, which reads closest to Alteryx semantics.",
            ),
            Option(
                "none",
                "None yet",
                25,
                tip="Budget for enablement — the migrated code is only as maintainable as the team's Spark fluency.",
            ),
        ],
    ),
    Question(
        "python_notebooks",
        "people",
        "How comfortable is the team with Python and notebooks?",
        [
            Option("strong", "Comfortable", 85),
            Option("some", "Some comfort", 60),
            Option(
                "dragdrop",
                "Drag-and-drop only",
                30,
                tip="Use the Lakeflow Designer output as a visual bridge from Alteryx's canvas while the team ramps on notebooks.",
            ),
        ],
    ),
    Question(
        "git_cicd",
        "people",
        "Do teams use Git / CI-CD for data pipelines?",
        [
            Option("mature", "Yes, mature practice", 90),
            Option(
                "basic",
                "Basic / occasional",
                60,
                tip="Adopt Databricks Repos and a simple CI check; a2d's `sync` fits a scheduled re-convert step.",
            ),
            Option(
                "none",
                "No source control",
                30,
                tip="Introduce Git before scaling the migration — otherwise generated code drifts and reviews get painful.",
            ),
        ],
    ),
    Question(
        "capacity",
        "people",
        "Is there dedicated capacity or a clear owner for the migration?",
        [
            Option("dedicated", "Yes, dedicated", 85),
            Option(
                "parttime",
                "Part-time / shared",
                55,
                tip="Shared capacity slips — protect a recurring block of time and a named owner.",
            ),
            Option(
                "none",
                "No owner yet",
                25,
                tip="Name an owner first; migrations without a driver stall after the easy wins.",
            ),
        ],
    ),
    # ── Platform & data landscape ──
    Question(
        "databricks_footprint",
        "platform",
        "What is your existing Databricks + Unity Catalog footprint?",
        [
            Option("uc", "Databricks with Unity Catalog standardized", 95),
            Option(
                "no_uc",
                "Databricks but no Unity Catalog",
                60,
                tip="Stand up Unity Catalog and a landing schema before converting Output tools — it is where the generated tables should land.",
            ),
            Option(
                "none",
                "Not on Databricks yet",
                30,
                tip="Provision a workspace + UC first; the converter's output assumes a catalog/schema to write into.",
            ),
        ],
    ),
    Question(
        "connections",
        "platform",
        "How do workflows source their data today?",
        [
            Option("cloud", "Cloud storage / database tables", 85),
            Option(
                "odbc",
                "Mix including ODBC / DSN connections",
                55,
                tip="Map each Alteryx connection to a UC table or JDBC URL with a connection-mapping YAML (`--connection-map`).",
            ),
            Option(
                "files",
                "Lots of Excel / network file-shares",
                35,
                tip="Excel and \\\\server\\share inputs must move to Volumes or cloud storage first — the converter flags every one with a WARNING.",
            ),
        ],
    ),
    Question(
        "data_volume",
        "platform",
        "What are your typical data volumes?",
        [
            Option("smallmed", "Small to medium", 80),
            Option(
                "large",
                "Large (100s of GB+)",
                65,
                tip="Right-size clusters with `a2d advise` and enable Photon for shuffle-heavy flows.",
            ),
            Option(
                "streaming",
                "Very large / streaming",
                55,
                tip="Consider Spark Structured Streaming / Lakeflow pipelines rather than a like-for-like batch port.",
            ),
        ],
    ),
    Question(
        "environments",
        "platform",
        "Do you have separate dev / test / prod environments?",
        [
            Option("yes", "Yes", 85),
            Option(
                "partial",
                "Partial",
                55,
                tip="Use Databricks Asset Bundles (`--generate-dab`) to promote the same pipeline across environments.",
            ),
            Option(
                "none",
                "No separation",
                35,
                tip="Establish at least dev/prod separation before go-live — DABs make this repeatable.",
            ),
        ],
    ),
    Question(
        "security_model",
        "platform",
        "Is data access governed centrally (roles / catalog grants)?",
        [
            Option("central", "Yes, centrally governed", 85),
            Option(
                "partial",
                "Partially",
                55,
                tip="Plan the catalog/schema/grant model up front so migrated tables inherit the right access.",
            ),
            Option(
                "manual",
                "Per-tool / manual",
                35,
                tip="Unity Catalog centralizes grants and gives you audit + lineage — design it before you migrate at scale.",
            ),
        ],
    ),
    # ── Governance & sponsorship ──
    Question(
        "sponsorship",
        "governance",
        "Is there executive sponsorship for the migration?",
        [
            Option("strong", "Strong, funded", 95),
            Option(
                "interested",
                "Interested but not committed",
                60,
                tip="Build the business case — the Savings estimator turns coverage and effort into dollars, payback and ROI you can show a sponsor.",
            ),
            Option(
                "none",
                "No sponsor",
                25,
                tip="Secure a sponsor first; without one, funding and prioritization won't hold.",
            ),
        ],
    ),
    Question(
        "budget",
        "governance",
        "Is budget allocated for the migration?",
        [
            Option("yes", "Yes", 85),
            Option(
                "partial",
                "Partial",
                55,
                tip="Size the ask with the Savings estimator so the budget maps to a payback period.",
            ),
            Option(
                "none",
                "Not yet",
                30,
                tip="Quantify the license + maintenance savings to justify the spend before committing scope.",
            ),
        ],
    ),
    Question(
        "timeline",
        "governance",
        "How much timeline pressure is there?",
        [
            Option("comfortable", "Comfortable", 80),
            Option(
                "moderate",
                "Moderate",
                60,
                tip="Phase the estate — convert high-coverage workflows first and defer the ML/spatial tail.",
            ),
            Option(
                "hard",
                "Hard external deadline",
                40,
                tip="A hard deadline means ruthless sequencing: use portfolio waves and cut the long-tail tools from phase one.",
            ),
        ],
    ),
    Question(
        "compliance",
        "governance",
        "Are there regulatory / compliance constraints on the data?",
        [
            Option("low", "Low", 85),
            Option(
                "some", "Some", 60, tip="Loop in security early; UC audit logs and lineage help evidence the controls."
            ),
            Option(
                "heavy",
                "Heavily regulated",
                45,
                tip="Regulated data lengthens sign-off — engage security/compliance before conversion, not after.",
            ),
        ],
    ),
    Question(
        "success_metrics",
        "governance",
        "Are success metrics defined for the migration?",
        [
            Option("yes", "Yes, defined", 85),
            Option(
                "vague",
                "Vague",
                55,
                tip="Define metrics (cost, run-time, # workflows live) and baseline them against the Savings estimate.",
            ),
            Option(
                "none",
                "None",
                30,
                tip="Without metrics you can't show progress — set a few measurable targets up front.",
            ),
        ],
    ),
]


def questions_by_dimension() -> dict[str, list[Question]]:
    """Group the bank by dimension id (in DIMENSIONS order)."""
    grouped: dict[str, list[Question]] = {dim: [] for dim in DIMENSIONS}
    for q in QUESTION_BANK:
        grouped.setdefault(q.dimension, []).append(q)
    return grouped


def question_index() -> dict[str, Question]:
    """Map question id → Question (ids are unique across the bank)."""
    return {q.id: q for q in QUESTION_BANK}
