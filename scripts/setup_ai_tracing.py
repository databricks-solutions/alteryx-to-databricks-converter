"""Set up MLflow tracing of the app's AI calls in a workspace, in one go.

Creates (or reuses) a Unity Catalog schema and an MLflow experiment whose traces
are stored in that schema, and gives the Databricks App's service principal
what it needs: CAN_EDIT on the experiment, USE CATALOG, and USE SCHEMA, SELECT
and MODIFY on the schema. Then set A2D_MLFLOW_EXPERIMENT to the experiment path
in the app's environment.

Why Unity Catalog: a Databricks App can reach the workspace host but not the
presigned storage URLs that experiment artifact storage uses, so with plain
experiment storage only trace summaries arrive, without spans. Traces stored in
UC go through the workspace host.

    python scripts/setup_ai_tracing.py --profile <profile> --app <app name> \\
        --catalog <catalog> --schema a2d_ai_traces \\
        --experiment /Users/<you>/a2d-ai-traces-uc --warehouse <sql warehouse id>
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, help="Databricks CLI profile for the workspace")
    ap.add_argument("--app", required=True, help="Databricks App name (its service principal gets access)")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", default="a2d_ai_traces")
    ap.add_argument("--experiment", required=True, help="Experiment path, e.g. /Users/<you>/a2d-ai-traces-uc")
    ap.add_argument("--table-prefix", default="a2d")
    ap.add_argument("--warehouse", required=True, help="SQL warehouse id MLflow uses to set up the tables")
    args = ap.parse_args(argv)

    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    os.environ.setdefault("MLFLOW_TRACKING_URI", "databricks")
    os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = args.warehouse
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

    import mlflow
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.catalog import PermissionsChange, Privilege, SecurableType
    from databricks.sdk.service.ml import ExperimentAccessControlRequest, ExperimentPermissionLevel
    from mlflow.entities.trace_location import UnityCatalog

    w = WorkspaceClient(profile=args.profile)
    sp = w.apps.get(args.app).service_principal_client_id
    if not sp:
        print(f"App {args.app} has no service principal", file=sys.stderr)
        return 1

    full_schema = f"{args.catalog}.{args.schema}"
    try:
        w.schemas.get(full_schema)
        print(f"schema {full_schema}: exists")
    except Exception:
        w.schemas.create(name=args.schema, catalog_name=args.catalog, comment="MLflow traces of the a2d app's AI calls")
        print(f"schema {full_schema}: created")

    existing = w.experiments.get_by_name(args.experiment).experiment if _exists(w, args.experiment) else None
    if existing is not None:
        exp = mlflow.set_experiment(experiment_id=existing.experiment_id)
        if exp.trace_location is None:
            print(
                f"experiment {args.experiment} exists but isn't linked to Unity Catalog. Use a new path; an "
                "experiment can only be linked before it has traces.",
                file=sys.stderr,
            )
            return 1
        print(f"experiment {args.experiment}: exists, traces in {exp.trace_location}")
    else:
        exp = mlflow.set_experiment(
            experiment_name=args.experiment,
            trace_location=UnityCatalog(
                catalog_name=args.catalog, schema_name=args.schema, table_prefix=args.table_prefix
            ),
        )
        print(f"experiment {args.experiment}: created ({exp.experiment_id}), traces in {exp.trace_location}")

    w.experiments.update_permissions(
        exp.experiment_id,
        access_control_list=[
            ExperimentAccessControlRequest(
                service_principal_name=sp, permission_level=ExperimentPermissionLevel.CAN_EDIT
            )
        ],
    )
    w.grants.update(
        SecurableType.CATALOG.value,
        args.catalog,
        changes=[PermissionsChange(principal=sp, add=[Privilege.USE_CATALOG])],
    )
    w.grants.update(
        SecurableType.SCHEMA.value,
        full_schema,
        changes=[PermissionsChange(principal=sp, add=[Privilege.USE_SCHEMA, Privilege.SELECT, Privilege.MODIFY])],
    )
    print(f"app {args.app} ({sp}): CAN_EDIT on the experiment; USE CATALOG; USE SCHEMA, SELECT, MODIFY on the schema")
    print(f'Set A2D_MLFLOW_EXPERIMENT="{args.experiment}" in the app\'s environment and redeploy.')
    return 0


def _exists(w, path: str) -> bool:
    try:
        return w.experiments.get_by_name(path).experiment is not None
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
