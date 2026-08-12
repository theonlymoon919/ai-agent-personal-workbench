from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text

from backend.app.cloud.models import TENANT_MODELS


def main() -> None:
    database_url = os.getenv("WORKBENCH_MIGRATION_DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("WORKBENCH_MIGRATION_DATABASE_URL is required")
    expected_tables = {model.__tablename__ for model in TENANT_MODELS}
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("select version_num from alembic_version"))
            rows = connection.execute(
                text(
                    """
                    select c.relname, c.relrowsecurity, c.relforcerowsecurity
                    from pg_class c
                    join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = current_schema() and c.relkind = 'r'
                    """
                )
            )
            rls = {name: (enabled, forced) for name, enabled, forced in rows}
            policy_tables = set(
                connection.scalars(
                    text("select distinct tablename from pg_policies where schemaname = current_schema()")
                )
            )
            runtime_role = connection.execute(
                text(
                    """
                    select rolcanlogin, rolsuper, rolbypassrls
                    from pg_roles where rolname = 'workbench_runtime'
                    """
                )
            ).one_or_none()
    finally:
        engine.dispose()

    missing = sorted(expected_tables - rls.keys())
    weak_rls = sorted(name for name in expected_tables if rls.get(name) != (True, True))
    missing_policies = sorted(expected_tables - policy_tables)
    problems: list[str] = []
    if revision != "0010_initial_admin_state":
        problems.append(f"unexpected migration head: {revision or 'missing'}")
    if missing:
        problems.append(f"missing tenant tables: {', '.join(missing)}")
    if weak_rls:
        problems.append(f"RLS is not enabled and forced: {', '.join(weak_rls)}")
    if missing_policies:
        problems.append(f"missing tenant policies: {', '.join(missing_policies)}")
    if runtime_role is None:
        problems.append("workbench_runtime role is missing")
    elif tuple(runtime_role) != (True, False, False):
        problems.append("workbench_runtime must be login-enabled without superuser or BYPASSRLS")
    if problems:
        print("Database security verification failed:")
        for problem in problems:
            print(f"- {problem}")
        raise SystemExit(1)
    print(
        f"Database security verification passed at {revision}: "
        f"{len(expected_tables)} tenant tables have forced RLS and policies."
    )


if __name__ == "__main__":
    main()
