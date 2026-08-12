from __future__ import annotations

import asyncio
import io
import json
import secrets
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from PIL import Image
from sqlalchemy import select

from backend.app.cloud.auth import AuthService
from backend.app.cloud.config import CloudSettings
from backend.app.cloud.database import CloudDatabase
from backend.app.cloud.models import User, Workspace
from backend.app.cloud.storage import LocalPrivateObjectStore
from backend.cloud_worker import process_deletions


@dataclass(slots=True)
class TemporaryIdentity:
    username: str
    password: str
    agent_token: str


async def create_identity(
    database: CloudDatabase,
    auth: AuthService,
    label: str,
) -> TemporaryIdentity:
    suffix = secrets.token_hex(6)
    username = f"qa_{label}_{suffix}"
    password = secrets.token_urlsafe(32)
    async with database.session_factory() as session:
        async with session.begin():
            user = await auth.create_user(session, username, f"QA {label}", password)
            workspace = await session.get(Workspace, user.workspace_id)
            if workspace is None:
                raise AssertionError("workspace was not created")
            agent = await auth.create_agent_credential(session, workspace)
    return TemporaryIdentity(username, password, agent.token)


async def login(base_url: str, identity: TemporaryIdentity) -> tuple[httpx.AsyncClient, str]:
    client = httpx.AsyncClient(base_url=base_url, timeout=30, follow_redirects=True)
    response = await client.post(
        "/api/auth/login",
        json={"username": identity.username, "password": identity.password},
    )
    if response.status_code != 200:
        raise AssertionError(f"login failed with {response.status_code}")
    return client, response.json()["csrf_token"]


def tiny_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (38, 104, 82)).save(buffer, format="PNG")
    return buffer.getvalue()


async def main() -> None:
    settings = CloudSettings.from_env()
    base_url = settings.public_origin
    database = CloudDatabase.create(settings)
    auth = AuthService(settings)
    first = await create_identity(database, auth, "a")
    second = await create_identity(database, auth, "b")
    first_client: httpx.AsyncClient | None = None
    second_client: httpx.AsyncClient | None = None

    try:
        first_client, first_csrf = await login(base_url, first)
        second_client, second_csrf = await login(base_url, second)
        first_headers = {"X-CSRF-Token": first_csrf}
        second_headers = {"X-CSRF-Token": second_csrf}

        created_task = await first_client.post(
            "/api/tasks",
            headers=first_headers,
            json={
                "title": "tenant-isolation-probe",
                "quadrant": "important_not_urgent",
                "note": "temporary QA record",
            },
        )
        if created_task.status_code != 201:
            raise AssertionError(f"task creation failed with {created_task.status_code}")
        task_id = created_task.json()["id"]

        first_tasks = await first_client.get("/api/tasks")
        second_tasks = await second_client.get("/api/tasks")
        if task_id not in {item["id"] for item in first_tasks.json()}:
            raise AssertionError("tenant A cannot read its own task")
        if task_id in {item["id"] for item in second_tasks.json()}:
            raise AssertionError("tenant B can read tenant A task")

        cross_user_update = await second_client.patch(
            f"/api/tasks/{task_id}",
            headers=second_headers,
            json={"done": True},
        )
        if cross_user_update.status_code != 404:
            raise AssertionError("tenant B user session can update tenant A task")

        first_agent_headers = {"Authorization": f"Bearer {first.agent_token}"}
        second_agent_headers = {"Authorization": f"Bearer {second.agent_token}"}
        own_agent_update = await first_client.patch(
            f"/api/agent/tasks/{task_id}",
            headers=first_agent_headers,
            json={"done": True},
        )
        if own_agent_update.status_code != 200:
            raise AssertionError("tenant A agent cannot update its own task")
        cross_agent_update = await second_client.patch(
            f"/api/agent/tasks/{task_id}",
            headers=second_agent_headers,
            json={"done": False},
        )
        if cross_agent_update.status_code != 404:
            raise AssertionError("tenant B agent can update tenant A task")

        created_plan = await first_client.post(
            "/api/growth/plans",
            headers=first_headers,
            json={"name": "tenant-learning-plan-probe", "goal": "temporary QA plan"},
        )
        if created_plan.status_code != 201:
            raise AssertionError(f"learning plan creation failed with {created_plan.status_code}")
        plan_id = created_plan.json()["id"]

        edited_plan = await first_client.patch(
            f"/api/growth/plans/{plan_id}",
            headers=first_headers,
            json={"name": "tenant-learning-plan-edited", "goal": "verify update", "status": "paused"},
        )
        if edited_plan.status_code != 200 or edited_plan.json()["name"] != "tenant-learning-plan-edited":
            raise AssertionError("tenant A cannot edit its own learning plan")

        for response, message in (
            (await second_client.get(f"/api/growth/plans/{plan_id}"), "read"),
            (await second_client.patch(f"/api/growth/plans/{plan_id}", headers=second_headers, json={"name": "blocked"}), "update"),
            (await second_client.delete(f"/api/growth/plans/{plan_id}", headers=second_headers), "delete"),
            (await second_client.post(f"/api/growth/plans/{plan_id}/restore", headers=second_headers), "restore"),
        ):
            if response.status_code != 404:
                raise AssertionError(f"tenant B can {message} tenant A learning plan")

        deleted_plan = await first_client.delete(
            f"/api/growth/plans/{plan_id}", headers=first_headers
        )
        if deleted_plan.status_code != 200 or not deleted_plan.json()["deleted"]:
            raise AssertionError("learning plan soft delete failed")
        if (await first_client.get(f"/api/growth/plans/{plan_id}")).status_code != 404:
            raise AssertionError("deleted learning plan remains readable as active")
        deleted_plans = await first_client.get("/api/growth/plans/deleted")
        if plan_id not in {item["id"] for item in deleted_plans.json()}:
            raise AssertionError("deleted learning plan is missing from recycle bin")
        dashboard = await first_client.get("/api/dashboard")
        if plan_id in {item["id"] for item in dashboard.json()["growth"]}:
            raise AssertionError("deleted learning plan remains on dashboard")

        generated_after_delete = await first_client.post(
            f"/api/agent/growth/plans/{plan_id}/generated",
            headers=first_agent_headers,
            json={
                "roadmap_markdown": "## should not be saved",
                "status": "active",
                "total_lessons": 1,
                "completed_lessons": 0,
                "resources": [],
            },
        )
        if generated_after_delete.status_code != 404:
            raise AssertionError("AI Agent can write to a deleted learning plan")

        for index in range(8):
            saved_content = await first_client.post(
                "/api/agent/content",
                headers=first_agent_headers,
                json={
                    "title": f"tenant-video-trend-{index}",
                    "category": "video_trend",
                    "source_url": f"https://example.com/qa-video/{secrets.token_hex(8)}/{index}",
                    "summary": "temporary QA content",
                    "platform": "qa",
                },
            )
            if saved_content.status_code != 201:
                raise AssertionError(f"agent content creation failed with {saved_content.status_code}")

        first_content_dashboard = await first_client.get("/api/dashboard")
        second_content_dashboard = await second_client.get("/api/dashboard")
        if len(first_content_dashboard.json()["content"]["video_trend"]) != 8:
            raise AssertionError("dashboard still truncates AI Agent content below the 12-item API limit")
        if second_content_dashboard.json()["content"]["video_trend"]:
            raise AssertionError("tenant B can read tenant A AI Agent content")

        restored_plan = await first_client.post(
            f"/api/growth/plans/{plan_id}/restore", headers=first_headers
        )
        if restored_plan.status_code != 200 or restored_plan.json()["deleted"]:
            raise AssertionError("learning plan restore failed")
        if (await first_client.get(f"/api/growth/plans/{plan_id}")).status_code != 200:
            raise AssertionError("restored learning plan is not readable")

        categories_response = await first_client.get("/api/finance/categories")
        if categories_response.status_code != 200:
            raise AssertionError("finance categories are unavailable")
        expense_category = next(
            (item for item in categories_response.json() if item["type"] == "expense"),
            None,
        )
        if expense_category is None:
            raise AssertionError("default expense category is missing")
        created_category = await first_client.post(
            "/api/finance/categories",
            headers=first_headers,
            json={
                "name": f"QA category {secrets.token_hex(4)}",
                "category_type": "expense",
                "icon": "qa",
                "color": "#267461",
            },
        )
        if created_category.status_code != 201:
            raise AssertionError(f"finance category creation failed with {created_category.status_code}")
        category_id = created_category.json()["id"]
        updated_category = await first_client.patch(
            f"/api/finance/categories/{category_id}",
            headers=first_headers,
            json={"name": f"QA category edited {secrets.token_hex(3)}", "active": False},
        )
        if updated_category.status_code != 200 or updated_category.json()["active"]:
            raise AssertionError("finance category update failed")
        cross_category_update = await second_client.patch(
            f"/api/finance/categories/{category_id}",
            headers=second_headers,
            json={"name": "blocked"},
        )
        if cross_category_update.status_code != 404:
            raise AssertionError("tenant B can update tenant A finance category")
        created_account = await first_client.post(
            "/api/finance/accounts",
            headers=first_headers,
            json={
                "name": f"QA wallet {secrets.token_hex(4)}",
                "account_type": "cash",
                "opening_balance_yuan": "500.00",
            },
        )
        if created_account.status_code != 201:
            raise AssertionError(f"finance account creation failed with {created_account.status_code}")
        account_id = created_account.json()["id"]
        updated_account = await first_client.patch(
            f"/api/finance/accounts/{account_id}",
            headers=first_headers,
            json={"name": f"QA wallet edited {secrets.token_hex(3)}", "account_type": "other"},
        )
        if updated_account.status_code != 200 or updated_account.json()["type"] != "other":
            raise AssertionError("finance account update failed")
        cross_account_update = await second_client.patch(
            f"/api/finance/accounts/{account_id}",
            headers=second_headers,
            json={"name": "blocked"},
        )
        if cross_account_update.status_code != 404:
            raise AssertionError("tenant B can update tenant A finance account")
        created_transaction = await first_client.post(
            "/api/finance/transactions",
            headers=first_headers,
            json={
                "transaction_type": "expense",
                "amount_yuan": "88.80",
                "local_date": "2026-08-04",
                "category_id": expense_category["id"],
                "account_id": account_id,
                "purpose": "tenant-finance-probe",
            },
        )
        if created_transaction.status_code != 201:
            raise AssertionError(f"finance transaction creation failed with {created_transaction.status_code}")
        transaction_id = created_transaction.json()["id"]
        accounts_with_balances = await first_client.get("/api/finance/accounts")
        account_snapshot = next(
            (item for item in accounts_with_balances.json() if item["id"] == account_id),
            None,
        )
        if account_snapshot is None or account_snapshot.get("current_balance_yuan") != "411.20":
            raise AssertionError("finance account balance did not deduct the expense")
        missing_account_transaction = await first_client.post(
            "/api/finance/transactions",
            headers=first_headers,
            json={
                "transaction_type": "expense",
                "amount_yuan": "1.00",
                "local_date": "2026-08-04",
                "category_id": expense_category["id"],
                "purpose": "missing-account-probe",
            },
        )
        if missing_account_transaction.status_code != 400:
            raise AssertionError("user finance transaction can be created without a real account")
        finance_page = await first_client.get(
            "/api/finance/transactions",
            params={"page": 1, "page_size": 1},
        )
        if finance_page.status_code != 200 or finance_page.json()["page_size"] != 1:
            raise AssertionError("finance server pagination failed")
        if transaction_id not in {item["id"] for item in finance_page.json()["items"]}:
            raise AssertionError("tenant A cannot read its paged finance transaction")
        for response, message in (
            (await second_client.get(f"/api/finance/transactions/{transaction_id}"), "read"),
            (
                await second_client.patch(
                    f"/api/finance/transactions/{transaction_id}",
                    headers=second_headers,
                    json={"amount_yuan": "1.00"},
                ),
                "update",
            ),
            (
                await second_client.delete(
                    f"/api/finance/transactions/{transaction_id}",
                    headers=second_headers,
                ),
                "delete",
            ),
        ):
            if response.status_code != 404:
                raise AssertionError(f"tenant B can {message} tenant A finance transaction")
        updated_transaction = await first_client.patch(
            f"/api/finance/transactions/{transaction_id}",
            headers=first_headers,
            json={"amount_yuan": "99.90", "purpose": "tenant-finance-edited"},
        )
        if updated_transaction.status_code != 200 or updated_transaction.json()["amount_yuan"] != "99.90":
            raise AssertionError("finance transaction update failed")
        deleted_transaction = await first_client.delete(
            f"/api/finance/transactions/{transaction_id}", headers=first_headers
        )
        if deleted_transaction.status_code != 200 or not deleted_transaction.json()["deleted"]:
            raise AssertionError("finance transaction soft delete failed")
        restored_transaction = await first_client.post(
            f"/api/finance/transactions/{transaction_id}/restore", headers=first_headers
        )
        if restored_transaction.status_code != 200 or restored_transaction.json()["deleted"]:
            raise AssertionError("finance transaction restore failed")

        today = date.today()
        month_start = today.replace(day=1)
        budget = await first_client.put(
            "/api/finance/budgets",
            headers=first_headers,
            json={
                "period_start": month_start.isoformat(),
                "period_end": today.isoformat(),
                "amount_yuan": "1200.00",
            },
        )
        if budget.status_code != 200 or budget.json()["amount_yuan"] != "1200.00":
            raise AssertionError("finance budget upsert failed")
        budgets = await first_client.get(
            "/api/finance/budgets",
            params={"start_date": month_start.isoformat(), "end_date": today.isoformat()},
        )
        if budgets.status_code != 200 or not budgets.json():
            raise AssertionError("finance budget listing failed")
        budget_id = budget.json()["id"]
        cross_budget_delete = await second_client.delete(
            f"/api/finance/budgets/{budget_id}", headers=second_headers
        )
        if cross_budget_delete.status_code != 404:
            raise AssertionError("tenant B can delete tenant A finance budget")
        deleted_budget = await first_client.delete(
            f"/api/finance/budgets/{budget_id}", headers=first_headers
        )
        if deleted_budget.status_code != 200 or not deleted_budget.json()["deleted"]:
            raise AssertionError("finance budget delete failed")
        budgets_after_delete = await first_client.get(
            "/api/finance/budgets",
            params={"start_date": month_start.isoformat(), "end_date": today.isoformat()},
        )
        if budget_id in {item["id"] for item in budgets_after_delete.json()}:
            raise AssertionError("deleted finance budget remains active")
        restored_budget = await first_client.put(
            "/api/finance/budgets",
            headers=first_headers,
            json={
                "period_start": month_start.isoformat(),
                "period_end": today.isoformat(),
                "amount_yuan": "1200.00",
            },
        )
        if restored_budget.status_code != 200 or restored_budget.json()["id"] != budget_id:
            raise AssertionError("deleted finance budget cannot be set again")
        goal = await first_client.post(
            "/api/finance/goals",
            headers=first_headers,
            json={
                "name": f"QA savings {secrets.token_hex(3)}",
                "target_amount_yuan": "3000.00",
                "current_amount_yuan": "300.00",
            },
        )
        if goal.status_code != 201:
            raise AssertionError("finance savings goal creation failed")
        goal_id = goal.json()["id"]
        updated_goal = await first_client.patch(
            f"/api/finance/goals/{goal_id}",
            headers=first_headers,
            json={"current_amount_yuan": "600.00", "status": "paused"},
        )
        if updated_goal.status_code != 200 or updated_goal.json()["status"] != "paused":
            raise AssertionError("finance savings goal update failed")
        insight = await first_client.post(
            "/api/finance/insights",
            headers=first_headers,
            json={
                "period_start": month_start.isoformat(),
                "period_end": today.isoformat(),
                "finding": "QA finding",
                "evidence": "QA evidence",
                "action": "QA action",
            },
        )
        if insight.status_code != 201:
            raise AssertionError("finance insight creation failed")
        summary = await first_client.get(
            "/api/finance/summary",
            params={"start_date": month_start.isoformat(), "end_date": today.isoformat()},
        )
        archive = await first_client.get(
            "/api/finance/archive",
            params={"start_month": month_start.isoformat(), "end_month": today.isoformat()},
        )
        if summary.status_code != 200 or "timeline" not in summary.json():
            raise AssertionError("finance aggregated summary failed")
        if archive.status_code != 200 or not isinstance(archive.json(), list):
            raise AssertionError("finance monthly archive failed")

        health_page = await first_client.get(
            "/api/health/records/page",
            params={"start_date": "2026-08-01", "end_date": "2026-08-31", "page": 1, "page_size": 8},
        )
        if health_page.status_code != 200 or "total_pages" not in health_page.json():
            raise AssertionError("health server pagination failed")

        upload = await first_client.post(
            "/api/uploads/meal",
            headers={**first_headers, "Idempotency-Key": f"qa-upload-{secrets.token_hex(8)}"},
            data={"record_date": "2026-08-04", "meal_slot": "lunch"},
            files={"file": ("qa-meal.png", tiny_png(), "image/png")},
        )
        if upload.status_code != 201:
            raise AssertionError(f"health image upload failed with {upload.status_code}")
        health_record = upload.json()
        record_id = health_record["id"]
        object_id = health_record["asset"].split("/", 1)[1]

        own_asset = await first_client.get(f"/api/workbench-assets/objects/{object_id}")
        cross_asset = await second_client.get(f"/api/workbench-assets/objects/{object_id}")
        if own_asset.status_code != 200 or cross_asset.status_code != 404:
            raise AssertionError("private user attachment isolation failed")

        own_agent_record = await first_client.get(
            f"/api/agent/health/records/{record_id}", headers=first_agent_headers
        )
        cross_agent_record = await second_client.get(
            f"/api/agent/health/records/{record_id}", headers=second_agent_headers
        )
        own_agent_asset = await first_client.get(
            f"/api/agent/assets/{object_id}", headers=first_agent_headers
        )
        cross_agent_asset = await second_client.get(
            f"/api/agent/assets/{object_id}", headers=second_agent_headers
        )
        if own_agent_record.status_code != 200 or cross_agent_record.status_code != 404:
            raise AssertionError("private agent health record isolation failed")
        if own_agent_asset.status_code != 200 or cross_agent_asset.status_code != 404:
            raise AssertionError("private agent attachment isolation failed")

        history = await first_client.get(
            "/api/health/history",
            params={
                "start_date": (today - timedelta(days=90)).isoformat(),
                "end_date": today.isoformat(),
            },
        )
        if history.status_code != 200:
            raise AssertionError(f"health aggregated history failed with {history.status_code}")
        history_body = history.json()
        for field in ("recent_start_date", "monthly_archive", "point_granularity"):
            if field not in history_body:
                raise AssertionError(f"health aggregated history is missing {field}")

        previous_password = second.password
        replacement_password = secrets.token_urlsafe(36)
        password_change = await second_client.post(
            "/api/account/password",
            headers=second_headers,
            json={
                "current_password": previous_password,
                "new_password": replacement_password,
            },
        )
        if password_change.status_code != 200:
            raise AssertionError(f"password change failed with {password_change.status_code}")
        await second_client.aclose()
        rejected_client = httpx.AsyncClient(base_url=base_url, timeout=30)
        rejected_login = await rejected_client.post(
            "/api/auth/login",
            json={"username": second.username, "password": previous_password},
        )
        await rejected_client.aclose()
        if rejected_login.status_code != 401:
            raise AssertionError("old password still works after password change")
        second.password = replacement_password
        second_client, second_csrf = await login(base_url, second)

        for client, csrf, identity in (
            (first_client, first_csrf, first),
            (second_client, second_csrf, second),
        ):
            deleted = await client.post(
                "/api/account/delete",
                headers={"X-CSRF-Token": csrf},
                json={"password": identity.password, "confirmation": "彻底删除我的数据"},
            )
            if deleted.status_code != 202:
                raise AssertionError(f"account deletion failed with {deleted.status_code}")

        purged = await process_deletions(
            database,
            LocalPrivateObjectStore(settings.data_root),
        )
        if purged != 2:
            raise AssertionError(f"expected 2 purged workspaces, received {purged}")

        async with database.session_factory() as session:
            remaining = await session.scalar(
                select(User.id).where(User.username.in_((first.username, second.username)))
            )
        if remaining is not None:
            raise AssertionError("temporary users were not purged")

        print(
            json.dumps(
                {
                    "passed": True,
                    "user_session_isolation": True,
                    "agent_token_isolation": True,
                    "attachment_isolation": True,
                    "learning_plan_isolation_and_lifecycle": True,
                    "hermes_content_count_and_isolation": True,
                    "finance_isolation_lifecycle_and_pagination": True,
                    "finance_budget_goal_insight_and_aggregates": True,
                    "health_pagination_and_long_range_aggregates": True,
                    "password_rotation": True,
                    "account_purge": True,
                }
            )
        )
    finally:
        if first_client is not None:
            await first_client.aclose()
        if second_client is not None:
            await second_client.aclose()
        # Keep failed smoke runs from leaving QA tenants behind. Credentials are
        # generated in memory and are never logged or written to disk.
        for identity in (first, second):
            cleanup_client: httpx.AsyncClient | None = None
            try:
                cleanup_client, cleanup_csrf = await login(base_url, identity)
                await cleanup_client.post(
                    "/api/account/delete",
                    headers={"X-CSRF-Token": cleanup_csrf},
                    json={
                        "password": identity.password,
                        "confirmation": "彻底删除我的数据",
                    },
                )
            except (AssertionError, httpx.HTTPError):
                pass
            finally:
                if cleanup_client is not None:
                    await cleanup_client.aclose()
        await process_deletions(database, LocalPrivateObjectStore(settings.data_root))
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
