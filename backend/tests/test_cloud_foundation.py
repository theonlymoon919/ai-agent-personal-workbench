from __future__ import annotations

import asyncio
import os
import re
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch
from io import BytesIO

from PIL import Image
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
from pydantic import ValidationError

from backend.app.cloud.api import create_cloud_app
from backend.app.cloud.config import CloudSettings
from backend.app.cloud.finance_repository import calculate_account_balance_minor, minor_to_yuan, yuan_to_minor
from backend.app.cloud.health_repository import compact_history_points
from backend.app.cloud.finance_schemas import (
    FinanceAccountUpdate,
    FinanceCategoryUpdate,
    FinanceTransactionCreate,
)
from backend.app.cloud.models import Base, FOUNDATION_TENANT_MODELS, InstanceState, TENANT_MODELS
from backend.app.cloud.security import (
    create_agent_token,
    create_invite_token,
    create_session_token,
    hash_password,
    parse_agent_token,
    parse_invite_token,
    parse_session_token,
    secret_digest,
    verify_password,
)
from backend.app.cloud.storage import LocalPrivateObjectStore
from backend.app.cloud.image_processing import normalize_health_image
from backend.app.cloud.rate_limit import MemoryRateLimiter
from backend.app.china_calendar import calendar_days
from backend.app.models import LearningPlanUpdate, ProjectPhaseCreate, TaskCreate, TaskUpdate


class CloudRateLimitTests(unittest.TestCase):
    def test_login_limiter_blocks_then_resets_a_key(self) -> None:
        limiter = MemoryRateLimiter(maximum=2, window_seconds=60)

        async def exercise() -> None:
            self.assertEqual(await limiter.consume("user@example.test|127.0.0.1"), (True, 0))
            self.assertEqual(await limiter.consume("user@example.test|127.0.0.1"), (True, 0))
            allowed, retry_after = await limiter.consume("user@example.test|127.0.0.1")
            self.assertFalse(allowed)
            self.assertGreaterEqual(retry_after, 1)
            await limiter.reset("user@example.test|127.0.0.1")
            self.assertEqual(await limiter.consume("user@example.test|127.0.0.1"), (True, 0))

        asyncio.run(exercise())


class CloudSecurityTests(unittest.TestCase):
    def test_session_and_agent_tokens_carry_only_public_workspace_routing(self) -> None:
        workspace_id = uuid.uuid4()
        session_token = create_session_token(workspace_id)
        agent_token = create_agent_token(workspace_id)

        self.assertEqual(parse_session_token(session_token).workspace_public_id, workspace_id)
        parsed_agent = parse_agent_token(agent_token)
        self.assertEqual(parsed_agent.workspace_public_id, workspace_id)
        self.assertEqual(len(parsed_agent.token_prefix), 8)
        self.assertNotIn("password", session_token)

    def test_invite_tokens_are_opaque_one_time_credentials(self) -> None:
        token = create_invite_token()
        parsed = parse_invite_token(token)
        self.assertTrue(token.startswith("wbi."))
        self.assertEqual(len(parsed.token_prefix), 8)
        self.assertEqual(parsed.token, token)
        with self.assertRaises(ValueError):
            parse_invite_token("wbi.invalid")

    def test_secret_digest_requires_server_pepper(self) -> None:
        token = create_session_token(uuid.uuid4())
        first = secret_digest(token, "a" * 32)
        second = secret_digest(token, "b" * 32)
        self.assertEqual(len(first), 32)
        self.assertNotEqual(first, second)

    def test_passwords_use_one_way_argon2_hashes(self) -> None:
        password_hash = hash_password("correct horse battery staple")
        valid, _ = verify_password("correct horse battery staple", password_hash)
        invalid, _ = verify_password("incorrect password", password_hash)
        self.assertTrue(password_hash.startswith("$argon2"))
        self.assertTrue(valid)
        self.assertFalse(invalid)


class CloudConfigurationTests(unittest.TestCase):
    def test_cloud_settings_reject_short_pepper(self) -> None:
        environment = {
            "WORKBENCH_DATABASE_URL": "postgresql+psycopg://user:pass@localhost/workbench",
            "WORKBENCH_TOKEN_PEPPER": "short",
            "WORKBENCH_PUBLIC_ORIGIN": "https://workbench.example.com",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "32"):
                CloudSettings.from_env()

    def test_cloud_settings_keep_pool_small_by_default(self) -> None:
        environment = {
            "WORKBENCH_DATABASE_URL": "postgresql+psycopg://user:pass@localhost/workbench",
            "WORKBENCH_TOKEN_PEPPER": "x" * 48,
            "WORKBENCH_PUBLIC_ORIGIN": "https://workbench.example.com",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = CloudSettings.from_env()
        self.assertEqual(settings.database_pool_size, 3)
        self.assertEqual(settings.database_max_overflow, 2)
        self.assertTrue(settings.secure_cookies)

    def test_cloud_settings_reject_origin_prefix_spoofing(self) -> None:
        environment = {
            "WORKBENCH_DATABASE_URL": "postgresql+psycopg://user:pass@localhost/workbench",
            "WORKBENCH_TOKEN_PEPPER": "x" * 48,
            "WORKBENCH_PUBLIC_ORIGIN": "http://localhost.attacker.example",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                CloudSettings.from_env()

    def test_cloud_settings_accept_exact_loopback_origin(self) -> None:
        environment = {
            "WORKBENCH_DATABASE_URL": "postgresql+psycopg://user:pass@localhost/workbench",
            "WORKBENCH_TOKEN_PEPPER": "x" * 48,
            "WORKBENCH_PUBLIC_ORIGIN": "http://127.0.0.1:8787/",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = CloudSettings.from_env()
        self.assertEqual(settings.public_origin, "http://127.0.0.1:8787")


class CloudFinanceContractTests(unittest.TestCase):
    def test_money_is_stored_as_integer_minor_units(self) -> None:
        from decimal import Decimal

        self.assertEqual(yuan_to_minor(Decimal("12.345")), 1235)
        self.assertEqual(minor_to_yuan(-125), "-1.25")

    def test_transaction_schema_rejects_incomplete_transfer(self) -> None:
        with self.assertRaises(ValidationError):
            FinanceTransactionCreate(transaction_type="transfer", amount_yuan="100")

    def test_transaction_schema_requires_expense_category(self) -> None:
        with self.assertRaises(ValidationError):
            FinanceTransactionCreate(transaction_type="expense", amount_yuan="20")

    def test_finance_account_balance_includes_every_money_flow(self) -> None:
        self.assertEqual(
            calculate_account_balance_minor(
                100_000,
                income_minor=25_000,
                expense_minor=8_800,
                refund_minor=800,
                transfer_in_minor=5_000,
                transfer_out_minor=12_000,
            ),
            110_000,
        )

    def test_cloud_contract_exposes_user_and_agent_finance_routes(self) -> None:
        settings = CloudSettings(
            database_url="postgresql+psycopg://user:pass@127.0.0.1/workbench",
            token_pepper="x" * 48,
            public_origin="https://workbench.example.com",
            data_root=Path("work/test-cloud-contract"),
        )
        app = create_cloud_app(settings)
        paths = app.openapi()["paths"]
        self.assertIn("/api/account/password", paths)
        self.assertIn("/api/account/username", paths)
        self.assertIn("/api/account/invites", paths)
        self.assertIn("/api/account/agent-token", paths)
        self.assertIn("/api/auth/setup-status", paths)
        self.assertIn("/api/auth/setup", paths)
        self.assertIn("/api/auth/register", paths)
        self.assertIn("/api/finance/transactions", paths)
        self.assertIn("/api/finance/accounts/{account_id}/detail", paths)
        self.assertIn("patch", paths["/api/finance/accounts/{account_id}"])
        self.assertIn("patch", paths["/api/finance/categories/{category_id}"])
        self.assertIn("get", paths["/api/finance/budgets"])
        self.assertIn("delete", paths["/api/finance/budgets/{budget_id}"])
        self.assertIn("get", paths["/api/health/records/page"])
        self.assertIn("/api/agent/finance/transactions", paths)
        self.assertIn("/api/agent/jobs/claim", paths)
        self.assertTrue(any(route.path == "/ws/agent" for route in app.routes))

    def test_finance_reference_updates_validate_supported_values(self) -> None:
        with self.assertRaises(ValidationError):
            FinanceAccountUpdate(account_type="crypto")
        with self.assertRaises(ValidationError):
            FinanceCategoryUpdate(name="")
        self.assertEqual(FinanceAccountUpdate(status="archived").status, "archived")


class CloudHealthArchiveTests(unittest.TestCase):
    @staticmethod
    def _points(count: int) -> list[dict]:
        start = date(2024, 1, 1)
        return [
            {
                "date": (start + timedelta(days=index)).isoformat(),
                "water_ml": 1000,
                "water_target_ml": 2000,
                "weight_kg": 60 + index / 100,
                "calories_kcal": 1500,
                "exercise_kcal": 20,
                "meal_count": 2,
                "has_record": True,
            }
            for index in range(count)
        ]

    def test_long_history_chart_points_are_bounded_and_keep_range_labels(self) -> None:
        daily_granularity, daily = compact_history_points(self._points(90), 2000)
        weekly_granularity, weekly = compact_history_points(self._points(365), 2000)
        monthly_granularity, monthly = compact_history_points(self._points(800), 2000)

        self.assertEqual(daily_granularity, "day")
        self.assertEqual(len(daily), 90)
        self.assertEqual(weekly_granularity, "week")
        self.assertLessEqual(len(weekly), 54)
        self.assertEqual(monthly_granularity, "month")
        self.assertLessEqual(len(monthly), 27)
        self.assertIn("period_start", weekly[0])
        self.assertIn("period_end", monthly[-1])


class CloudMcpContractTests(unittest.TestCase):
    def test_cloud_contract_exposes_authenticated_mcp_tools(self) -> None:
        settings = CloudSettings(
            database_url="postgresql+psycopg://user:pass@127.0.0.1/workbench",
            token_pepper="x" * 48,
            public_origin="https://workbench.example.com",
            data_root=Path("work/test-cloud-mcp-contract"),
        )
        app = create_cloud_app(settings)
        self.assertTrue(any(route.path == "/mcp" for route in app.routes))
        tools = set(app.state.cloud_mcp._tool_manager._tools)
        self.assertGreaterEqual(len(tools), 20)
        self.assertTrue(
            {
                "claim_next_agent_job",
                "load_health_image",
                "save_health_record_analysis",
                "create_finance_transaction",
                "save_generated_learning_plan",
                "save_content_item",
            }.issubset(tools)
        )
        with TestClient(app) as client:
            response = client.post(
                "/mcp/",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
        self.assertEqual(response.status_code, 401)


class CloudGrowthContractTests(unittest.TestCase):
    def test_authenticated_transactions_finish_before_the_response_is_sent(self) -> None:
        settings = CloudSettings(
            database_url="postgresql+psycopg://user:pass@127.0.0.1/workbench",
            token_pepper="x" * 48,
            public_origin="https://workbench.example.com",
            data_root=Path("work/test-cloud-transaction-scope"),
        )
        app = create_cloud_app(settings)
        transaction_dependencies = [
            dependency
            for route in app.routes
            if isinstance(route, APIRoute)
            for dependency in route.dependant.dependencies
            if getattr(dependency.call, "__name__", "") in {"current_context", "agent_context"}
        ]

        self.assertGreater(len(transaction_dependencies), 100)
        self.assertTrue(
            all(dependency.scope == "function" for dependency in transaction_dependencies),
            "database transactions must commit before clients receive a successful response",
        )

    def test_learning_plan_user_routes_cover_edit_delete_and_restore(self) -> None:
        settings = CloudSettings(
            database_url="postgresql+psycopg://user:pass@127.0.0.1/workbench",
            token_pepper="x" * 48,
            public_origin="https://workbench.example.com",
            data_root=Path("work/test-cloud-growth-contract"),
        )
        paths = create_cloud_app(settings).openapi()["paths"]
        self.assertIn("get", paths["/api/growth/plans"])
        self.assertIn("get", paths["/api/growth/plans/deleted"])
        self.assertIn("patch", paths["/api/growth/plans/{plan_id}"])
        self.assertIn("delete", paths["/api/growth/plans/{plan_id}"])
        self.assertIn("post", paths["/api/growth/plans/{plan_id}/restore"])

    def test_learning_plan_update_schema_rejects_an_empty_name(self) -> None:
        with self.assertRaises(ValidationError):
            LearningPlanUpdate(name="")
        payload = LearningPlanUpdate(name="吉他进阶", goal="完成三首弹唱", status="paused")
        self.assertEqual(payload.model_dump(exclude_unset=True)["status"], "paused")

    def test_september_2026_calendar_includes_term_festival_and_holiday_details(self) -> None:
        rows, notices = calendar_days(date(2026, 9, 20), date(2026, 10, 7))
        by_date = {row["date"]: row for row in rows}
        self.assertEqual(by_date["2026-09-23"]["solar_term"], "秋分")
        self.assertIn("中秋节", by_date["2026-09-25"]["traditional_festivals"])
        self.assertEqual(by_date["2026-09-25"]["official_holiday"]["label"], "中秋假期")
        self.assertEqual(by_date["2026-09-20"]["official_holiday"]["kind"], "makeup_workday")
        self.assertEqual(notices[0]["status"], "official")


class CloudProjectPlanningContractTests(unittest.TestCase):
    @staticmethod
    def app():
        settings = CloudSettings(
            database_url="postgresql+psycopg://user:pass@127.0.0.1/workbench",
            token_pepper="x" * 48,
            public_origin="https://workbench.example.com",
            data_root=Path("work/test-project-planning-contract"),
        )
        return create_cloud_app(settings)

    def test_user_and_agent_routes_have_matching_project_crud(self) -> None:
        paths = self.app().openapi()["paths"]
        route_pairs = (
            ("/api/projects", "/api/agent/projects", ("get", "post")),
            ("/api/projects/{project_id}", "/api/agent/projects/{project_id}", ("patch", "delete")),
            ("/api/projects/{project_id}/restore", "/api/agent/projects/{project_id}/restore", ("post",)),
            ("/api/projects/{project_id}/plan", "/api/agent/projects/{project_id}/plan", ("get",)),
            ("/api/projects/{project_id}/phases", "/api/agent/projects/{project_id}/phases", ("get", "post")),
            ("/api/project-phases/{phase_id}", "/api/agent/project-phases/{phase_id}", ("patch", "delete")),
            ("/api/project-phases/{phase_id}/restore", "/api/agent/project-phases/{phase_id}/restore", ("post",)),
            ("/api/tasks/{task_id}", "/api/agent/tasks/{task_id}", ("patch", "delete")),
            ("/api/tasks/{task_id}/restore", "/api/agent/tasks/{task_id}/restore", ("post",)),
        )
        for user_path, agent_path, methods in route_pairs:
            for method in methods:
                self.assertIn(method, paths[user_path], f"{user_path} 缺少 {method}")
                self.assertIn(method, paths[agent_path], f"{agent_path} 缺少 {method}")

    def test_agent_upload_and_health_record_crud_match_user_capabilities(self) -> None:
        paths = self.app().openapi()["paths"]
        self.assertIn("post", paths["/api/uploads/{kind}"])
        self.assertIn("post", paths["/api/agent/uploads/{kind}"])
        for method in ("patch", "delete"):
            self.assertIn(method, paths["/api/health/records/{record_id}"])
            self.assertIn(method, paths["/api/agent/health/records/{record_id}"])
        self.assertIn("post", paths["/api/health/records/{record_id}/restore"])
        self.assertIn("post", paths["/api/agent/health/records/{record_id}/restore"])

    def test_mcp_exposes_full_project_and_recycle_bin_workflow(self) -> None:
        tools = set(self.app().state.cloud_mcp._tool_manager._tools)
        expected = {
            "list_projects", "get_project_plan", "create_project", "update_project",
            "delete_project", "restore_project", "list_project_phases",
            "create_project_phase", "update_project_phase", "delete_project_phase",
            "restore_project_phase", "create_task", "update_task", "delete_task", "restore_task",
            "update_health_record", "delete_health_record", "restore_health_record",
        }
        self.assertTrue(expected.issubset(tools), sorted(expected - tools))

    def test_planning_schemas_accept_project_context_and_dates(self) -> None:
        project_id, phase_id, predecessor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        task = TaskCreate(
            title="完成交互原型",
            project_id=project_id,
            phase_id=phase_id,
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 14),
            status="in_progress",
            progress_percent=40,
            predecessor_ids=[predecessor_id],
        )
        self.assertEqual(task.project_id, project_id)
        self.assertEqual(task.progress_percent, 40)
        self.assertIsNone(TaskUpdate(project_id=None).project_id)
        self.assertEqual(ProjectPhaseCreate(name="产品定义").status, "active")


class CloudObjectStorageTests(unittest.TestCase):
    def test_private_object_keys_ignore_original_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LocalPrivateObjectStore(Path(temporary))
            workspace_id = uuid.uuid4()
            object_id = uuid.uuid4()
            key = store.build_key(
                workspace_id,
                object_id,
                "image/jpeg",
                datetime(2026, 8, 4, tzinfo=timezone.utc),
            )
            saved = store.put_bytes(key, b"private-image")
            self.assertEqual(saved.size_bytes, 13)
            self.assertEqual(store.path_for_read(key).read_bytes(), b"private-image")
            self.assertIn(str(workspace_id), key)
            self.assertNotIn("breakfast", key)

    def test_private_object_store_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LocalPrivateObjectStore(Path(temporary))
            with self.assertRaises(ValueError):
                store.put_bytes("../../outside.jpg", b"blocked")

    def test_workspace_purge_removes_only_the_selected_tenant_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LocalPrivateObjectStore(Path(temporary))
            selected = uuid.uuid4()
            neighbor = uuid.uuid4()
            selected_key = store.build_key(selected, uuid.uuid4(), "image/jpeg")
            neighbor_key = store.build_key(neighbor, uuid.uuid4(), "image/jpeg")
            store.put_bytes(selected_key, b"selected")
            store.put_bytes(neighbor_key, b"neighbor")
            self.assertTrue(store.delete_workspace(selected))
            self.assertFalse((Path(temporary) / "workspaces" / str(selected)).exists())
            self.assertEqual(store.path_for_read(neighbor_key).read_bytes(), b"neighbor")

    def test_uploaded_image_is_normalized_and_thumbnail_is_created(self) -> None:
        source = BytesIO()
        Image.new("RGB", (1800, 1200), "#2f6b57").save(source, format="JPEG", quality=95)
        normalized = normalize_health_image(source.getvalue())
        self.assertEqual(normalized.content_type, "image/webp")
        self.assertLessEqual(max(normalized.width, normalized.height), 2560)
        with Image.open(BytesIO(normalized.thumbnail_content)) as thumbnail:
            self.assertLessEqual(max(thumbnail.size), 640)


class CloudSchemaTests(unittest.TestCase):
    def test_every_tenant_table_has_workspace_id_and_workspace_first_index(self) -> None:
        for model in TENANT_MODELS:
            table = model.__table__
            self.assertIn("workspace_id", table.c, table.name)
            indexed = any(
                tuple(column.name for column in index.columns)[:1] == ("workspace_id",)
                for index in table.indexes
            )
            unique_workspace = any(
                tuple(column.name for column in constraint.columns) == ("workspace_id",)
                for constraint in table.constraints
                if hasattr(constraint, "columns")
            )
            self.assertTrue(indexed or unique_workspace, table.name)

    def test_every_foreign_key_has_a_supporting_index_or_unique_constraint(self) -> None:
        for table in Base.metadata.tables.values():
            indexed_columns = {
                tuple(column.name for column in index.columns)
                for index in table.indexes
            }
            indexed_columns.update(
                tuple(column.name for column in constraint.columns)
                for constraint in table.constraints
                if getattr(constraint, "unique", False) or constraint.__class__.__name__ in {"PrimaryKeyConstraint", "UniqueConstraint"}
            )
            for foreign_key in table.foreign_key_constraints:
                columns = tuple(column.name for column in foreign_key.columns)
                self.assertTrue(
                    any(candidate[: len(columns)] == columns for candidate in indexed_columns),
                    f"{table.name}.{columns} 缺少索引",
                )

    def test_migration_enables_and_forces_rls_for_all_tenant_tables(self) -> None:
        versions = Path(__file__).resolve().parents[1] / "migrations" / "versions"
        migrations = []
        sources = []
        filenames = (
            "0001_cloud_foundation.py",
            "0002_core_workbench.py",
            "0003_health_history.py",
            "0004_finance.py",
            "0005_growth_content.py",
            "0006_account_deletion.py",
            "0009_project_planning.py",
        )
        for index, filename in enumerate(filenames):
            revision_path = versions / filename
            spec = spec_from_file_location(f"cloud_revision_{index}", revision_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader if spec else None)
            revision = module_from_spec(spec)
            spec.loader.exec_module(revision)
            migrations.extend(revision.TENANT_TABLES)
            sources.append(revision_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(migrations),
            {model.__tablename__ for model in TENANT_MODELS},
        )
        self.assertEqual(
            set(migrations[: len(FOUNDATION_TENANT_MODELS)]),
            {model.__tablename__ for model in FOUNDATION_TENANT_MODELS},
        )
        source = "\n".join(sources)
        self.assertIn("enable row level security", source)
        self.assertIn("force row level security", source)
        self.assertIn("current_setting('app.current_workspace_id'", source)
        self.assertIn("agent_credentials_one_active_per_workspace_idx", source)
        self.assertIn("purge_current_workspace", source)

    def test_invitation_migration_does_not_bind_permission_to_a_username(self) -> None:
        revision = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "0008_invite_registration.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("username_normalized =", revision)
        self.assertIn("order by created_at, id limit 1", revision)

    def test_initial_setup_state_is_permanent_and_identity_neutral(self) -> None:
        revision = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "0010_ensure_initial_admin_inviter.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(InstanceState.__tablename__, "instance_state")
        self.assertNotIn("username_normalized", revision)
        self.assertIn("insert into instance_state", revision)
        self.assertIn("where exists (select 1 from users)", revision)
        self.assertIn("grant select, insert on instance_state", revision)

    def test_alembic_revision_ids_fit_the_version_table(self) -> None:
        versions = Path(__file__).resolve().parents[1] / "migrations" / "versions"
        revision_ids = []
        for revision_path in versions.glob("*.py"):
            source = revision_path.read_text(encoding="utf-8")
            match = re.search(r'^revision:\s*str\s*=\s*"([^"]+)"', source, re.MULTILINE)
            self.assertIsNotNone(match, f"{revision_path.name} is missing a revision ID")
            revision_id = match.group(1)
            self.assertLessEqual(
                len(revision_id),
                32,
                f"{revision_path.name} exceeds Alembic's default version_num length",
            )
            revision_ids.append(revision_id)
        self.assertEqual(len(revision_ids), len(set(revision_ids)))


if __name__ == "__main__":
    unittest.main()
