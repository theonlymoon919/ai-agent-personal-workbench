from __future__ import annotations

import base64
import calendar
import json
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .core_repository import CoreRepository
from .jobs import enqueue_job
from .models import (
    FinanceAccount,
    FinanceBudget,
    FinanceCategory,
    FinanceInsight,
    FinanceMonthlySummary,
    FinanceRecurringRule,
    FinanceTransaction,
    SavingsGoal,
)


DEFAULT_CATEGORIES = (
    ("income", "salary", "工资", "wallet", "#2f6b57"),
    ("income", "bonus", "奖金", "sparkles", "#5b7f6f"),
    ("income", "other_income", "其他收入", "plus", "#7b9488"),
    ("expense", "food", "餐饮", "utensils", "#d46f4c"),
    ("expense", "housing", "居住", "house", "#a87855"),
    ("expense", "transport", "交通", "car", "#537d91"),
    ("expense", "shopping", "购物", "shopping-bag", "#b06b82"),
    ("expense", "health", "健康", "heart", "#c35c64"),
    ("expense", "education", "学习", "book-open", "#6b6fa4"),
    ("expense", "entertainment", "娱乐", "film", "#8e6d9b"),
    ("expense", "social", "人情社交", "users", "#b88a4c"),
    ("expense", "digital", "数码", "laptop", "#557680"),
    ("expense", "subscription", "订阅", "repeat", "#7a7794"),
    ("expense", "other_expense", "其他支出", "more-horizontal", "#8c8c86"),
)


def yuan_to_minor(value: Decimal) -> int:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(quantized * 100)


def minor_to_yuan(value: int) -> str:
    return f"{Decimal(value) / Decimal(100):.2f}"


def calculate_account_balance_minor(
    opening_balance_minor: int,
    *,
    income_minor: int = 0,
    expense_minor: int = 0,
    refund_minor: int = 0,
    transfer_in_minor: int = 0,
    transfer_out_minor: int = 0,
) -> int:
    """Return the live balance represented by an account's complete money flow."""
    return (
        opening_balance_minor
        + income_minor
        + refund_minor
        + transfer_in_minor
        - expense_minor
        - transfer_out_minor
    )


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    return date(value.year + (1 if value.month == 12 else 0), 1 if value.month == 12 else value.month + 1, 1)


def _month_end(value: date) -> date:
    return date.fromordinal(_next_month(_month_start(value)).toordinal() - 1)


def _cursor_encode(occurred_at: datetime, internal_id: int) -> str:
    payload = json.dumps([occurred_at.isoformat(), internal_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _cursor_decode(value: str) -> tuple[datetime, int]:
    try:
        padded = value + "=" * (-len(value) % 4)
        occurred_at, internal_id = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return datetime.fromisoformat(occurred_at), int(internal_id)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("分页位置无效，请刷新后重试") from exc


class FinanceRepository:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: int,
        actor_type: str,
        actor_public_id: uuid.UUID | None,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.actor_type = actor_type
        self.actor_public_id = actor_public_id
        self.timezone_name = timezone_name
        self.core = CoreRepository(session, workspace_id, actor_type, actor_public_id, timezone_name)

    async def ensure_defaults(self) -> None:
        await self.session.execute(select(func.pg_advisory_xact_lock(self.workspace_id)))
        existing_keys = set(
            (
                await self.session.scalars(
                    select(FinanceCategory.system_key).where(
                        FinanceCategory.workspace_id == self.workspace_id,
                        FinanceCategory.system_key.is_not(None),
                    )
                )
            ).all()
        )
        for order, (category_type, system_key, name, icon, color) in enumerate(DEFAULT_CATEGORIES):
            if system_key in existing_keys:
                continue
            self.session.add(
                FinanceCategory(
                    workspace_id=self.workspace_id,
                    category_type=category_type,
                    system_key=system_key,
                    name=name,
                    icon=icon,
                    color=color,
                    sort_order=order,
                )
            )
        default_account = await self.session.scalar(
            select(FinanceAccount.id).where(
                FinanceAccount.workspace_id == self.workspace_id,
                FinanceAccount.name == "未指定账户",
            )
        )
        if default_account is None:
            self.session.add(
                FinanceAccount(
                    workspace_id=self.workspace_id,
                    name="未指定账户",
                    account_type="other",
                )
            )
        await self.session.flush()

    @staticmethod
    def category_payload(category: FinanceCategory) -> dict:
        return {
            "id": str(category.public_id),
            "type": category.category_type,
            "name": category.name,
            "system_key": category.system_key,
            "icon": category.icon,
            "color": category.color,
            "active": category.active,
        }

    @staticmethod
    def account_payload(account: FinanceAccount, metrics: dict | None = None) -> dict:
        payload = {
            "id": str(account.public_id),
            "name": account.name,
            "type": account.account_type,
            "currency": account.currency,
            "opening_balance_minor": account.opening_balance_minor,
            "opening_balance_yuan": minor_to_yuan(account.opening_balance_minor),
            "status": account.status,
            "is_placeholder": account.name == "未指定账户",
        }
        if metrics is not None:
            income = int(metrics.get("income_minor", 0) or 0)
            expense = int(metrics.get("expense_minor", 0) or 0)
            refund = int(metrics.get("refund_minor", 0) or 0)
            transfer_in = int(metrics.get("transfer_in_minor", 0) or 0)
            transfer_out = int(metrics.get("transfer_out_minor", 0) or 0)
            current = calculate_account_balance_minor(
                account.opening_balance_minor,
                income_minor=income,
                expense_minor=expense,
                refund_minor=refund,
                transfer_in_minor=transfer_in,
                transfer_out_minor=transfer_out,
            )
            payload.update(
                {
                    "current_balance_minor": current,
                    "current_balance_yuan": minor_to_yuan(current),
                    "income_minor": income,
                    "income_yuan": minor_to_yuan(income),
                    "expense_minor": expense,
                    "expense_yuan": minor_to_yuan(expense),
                    "refund_minor": refund,
                    "refund_yuan": minor_to_yuan(refund),
                    "transfer_in_minor": transfer_in,
                    "transfer_in_yuan": minor_to_yuan(transfer_in),
                    "transfer_out_minor": transfer_out,
                    "transfer_out_yuan": minor_to_yuan(transfer_out),
                    "transaction_count": int(metrics.get("transaction_count", 0) or 0),
                    "last_transaction_at": (
                        metrics["last_transaction_at"].isoformat()
                        if metrics.get("last_transaction_at")
                        else None
                    ),
                }
            )
        return payload

    async def list_categories(self, include_inactive: bool = False) -> list[dict]:
        await self.ensure_defaults()
        statement = select(FinanceCategory).where(FinanceCategory.workspace_id == self.workspace_id)
        if not include_inactive:
            statement = statement.where(FinanceCategory.active.is_(True))
        categories = list((await self.session.scalars(statement.order_by(FinanceCategory.sort_order, FinanceCategory.id))).all())
        return [self.category_payload(item) for item in categories]

    async def create_category(
        self, category_type: str, name: str, icon: str = "", color: str = ""
    ) -> dict:
        await self.ensure_defaults()
        cleaned = " ".join(name.split()).strip()
        if not cleaned:
            raise ValueError("分类名称不能为空")
        duplicate = await self.session.scalar(
            select(FinanceCategory.id).where(
                FinanceCategory.workspace_id == self.workspace_id,
                FinanceCategory.category_type == category_type,
                FinanceCategory.name == cleaned,
            )
        )
        if duplicate is not None:
            raise ValueError("这个分类已经存在")
        category = FinanceCategory(
            workspace_id=self.workspace_id,
            category_type=category_type,
            name=cleaned,
            icon=icon,
            color=color,
            sort_order=1000,
        )
        self.session.add(category)
        await self.session.flush()
        self.core._changed("finance.category_created", "finance_category", str(category.public_id), "create_finance_category")
        return self.category_payload(category)

    async def update_category(self, public_id: uuid.UUID, changes: dict) -> dict:
        category = await self.session.scalar(
            select(FinanceCategory).where(
                FinanceCategory.workspace_id == self.workspace_id,
                FinanceCategory.public_id == public_id,
            )
        )
        if category is None:
            raise KeyError(str(public_id))
        if changes.get("name") is not None:
            cleaned = " ".join(changes["name"].split()).strip()
            duplicate = await self.session.scalar(
                select(FinanceCategory.id).where(
                    FinanceCategory.workspace_id == self.workspace_id,
                    FinanceCategory.category_type == category.category_type,
                    FinanceCategory.name == cleaned,
                    FinanceCategory.id != category.id,
                )
            )
            if duplicate is not None:
                raise ValueError("这个分类已经存在")
            category.name = cleaned
        for key in ("icon", "color", "active"):
            if key in changes and changes[key] is not None:
                setattr(category, key, changes[key].strip() if isinstance(changes[key], str) else changes[key])
        category.updated_at = datetime.now(timezone.utc)
        self.core._changed(
            "finance.category_updated",
            "finance_category",
            str(category.public_id),
            "update_finance_category",
        )
        await self.session.flush()
        return self.category_payload(category)

    async def list_accounts(self, include_archived: bool = False) -> list[dict]:
        await self.ensure_defaults()
        statement = select(FinanceAccount).where(FinanceAccount.workspace_id == self.workspace_id)
        if not include_archived:
            statement = statement.where(FinanceAccount.status == "active")
        accounts = list((await self.session.scalars(statement.order_by(FinanceAccount.id))).all())
        primary_rows = list(
            (
                await self.session.execute(
                    select(
                        FinanceTransaction.account_id,
                        func.coalesce(
                            func.sum(FinanceTransaction.amount_minor).filter(
                                FinanceTransaction.transaction_type == "income"
                            ),
                            0,
                        ).label("income_minor"),
                        func.coalesce(
                            func.sum(FinanceTransaction.amount_minor).filter(
                                FinanceTransaction.transaction_type == "expense"
                            ),
                            0,
                        ).label("expense_minor"),
                        func.coalesce(
                            func.sum(FinanceTransaction.amount_minor).filter(
                                FinanceTransaction.transaction_type == "refund"
                            ),
                            0,
                        ).label("refund_minor"),
                        func.coalesce(
                            func.sum(FinanceTransaction.amount_minor).filter(
                                FinanceTransaction.transaction_type == "transfer"
                            ),
                            0,
                        ).label("transfer_out_minor"),
                        func.count(FinanceTransaction.id).label("transaction_count"),
                        func.max(FinanceTransaction.occurred_at).label("last_transaction_at"),
                    )
                    .where(
                        FinanceTransaction.workspace_id == self.workspace_id,
                        FinanceTransaction.account_id.is_not(None),
                        FinanceTransaction.deleted_at.is_(None),
                    )
                    .group_by(FinanceTransaction.account_id)
                )
            ).all()
        )
        transfer_in_rows = list(
            (
                await self.session.execute(
                    select(
                        FinanceTransaction.to_account_id,
                        func.coalesce(func.sum(FinanceTransaction.amount_minor), 0).label("transfer_in_minor"),
                        func.count(FinanceTransaction.id).label("transaction_count"),
                        func.max(FinanceTransaction.occurred_at).label("last_transaction_at"),
                    )
                    .where(
                        FinanceTransaction.workspace_id == self.workspace_id,
                        FinanceTransaction.transaction_type == "transfer",
                        FinanceTransaction.to_account_id.is_not(None),
                        FinanceTransaction.deleted_at.is_(None),
                    )
                    .group_by(FinanceTransaction.to_account_id)
                )
            ).all()
        )
        metrics: dict[int, dict] = {
            int(row.account_id): {
                "income_minor": int(row.income_minor or 0),
                "expense_minor": int(row.expense_minor or 0),
                "refund_minor": int(row.refund_minor or 0),
                "transfer_out_minor": int(row.transfer_out_minor or 0),
                "transaction_count": int(row.transaction_count or 0),
                "last_transaction_at": row.last_transaction_at,
            }
            for row in primary_rows
        }
        for row in transfer_in_rows:
            account_metrics = metrics.setdefault(int(row.to_account_id), {})
            account_metrics["transfer_in_minor"] = int(row.transfer_in_minor or 0)
            account_metrics["transaction_count"] = int(account_metrics.get("transaction_count", 0)) + int(
                row.transaction_count or 0
            )
            previous_last = account_metrics.get("last_transaction_at")
            if previous_last is None or (row.last_transaction_at and row.last_transaction_at > previous_last):
                account_metrics["last_transaction_at"] = row.last_transaction_at
        return [self.account_payload(item, metrics.get(item.id, {})) for item in accounts]

    async def account_detail(self, public_id: uuid.UUID, selected_date: date) -> dict:
        account = await self.session.scalar(
            select(FinanceAccount).where(
                FinanceAccount.workspace_id == self.workspace_id,
                FinanceAccount.public_id == public_id,
            )
        )
        if account is None or account.name == "未指定账户":
            raise KeyError(str(public_id))

        def aggregate_statement(*extra_conditions):
            relevant = or_(
                FinanceTransaction.account_id == account.id,
                FinanceTransaction.to_account_id == account.id,
            )
            return select(
                func.count(FinanceTransaction.id).label("transaction_count"),
                func.coalesce(
                    func.sum(FinanceTransaction.amount_minor).filter(
                        and_(
                            FinanceTransaction.account_id == account.id,
                            FinanceTransaction.transaction_type == "income",
                        )
                    ),
                    0,
                ).label("income_minor"),
                func.coalesce(
                    func.sum(FinanceTransaction.amount_minor).filter(
                        and_(
                            FinanceTransaction.account_id == account.id,
                            FinanceTransaction.transaction_type == "expense",
                        )
                    ),
                    0,
                ).label("expense_minor"),
                func.coalesce(
                    func.sum(FinanceTransaction.amount_minor).filter(
                        and_(
                            FinanceTransaction.account_id == account.id,
                            FinanceTransaction.transaction_type == "refund",
                        )
                    ),
                    0,
                ).label("refund_minor"),
                func.coalesce(
                    func.sum(FinanceTransaction.amount_minor).filter(
                        and_(
                            FinanceTransaction.to_account_id == account.id,
                            FinanceTransaction.transaction_type == "transfer",
                        )
                    ),
                    0,
                ).label("transfer_in_minor"),
                func.coalesce(
                    func.sum(FinanceTransaction.amount_minor).filter(
                        and_(
                            FinanceTransaction.account_id == account.id,
                            FinanceTransaction.transaction_type == "transfer",
                        )
                    ),
                    0,
                ).label("transfer_out_minor"),
            ).where(
                FinanceTransaction.workspace_id == self.workspace_id,
                FinanceTransaction.deleted_at.is_(None),
                relevant,
                *extra_conditions,
            )

        day_row = (
            await self.session.execute(
                aggregate_statement(FinanceTransaction.local_date == selected_date)
            )
        ).one()
        cumulative_row = (
            await self.session.execute(
                aggregate_statement(FinanceTransaction.local_date <= selected_date)
            )
        ).one()

        def row_metrics(row) -> dict[str, int]:
            return {
                "income_minor": int(row.income_minor or 0),
                "expense_minor": int(row.expense_minor or 0),
                "refund_minor": int(row.refund_minor or 0),
                "transfer_in_minor": int(row.transfer_in_minor or 0),
                "transfer_out_minor": int(row.transfer_out_minor or 0),
                "transaction_count": int(row.transaction_count or 0),
            }

        day_metrics = row_metrics(day_row)
        cumulative_metrics = row_metrics(cumulative_row)
        day_change = calculate_account_balance_minor(0, **{key: value for key, value in day_metrics.items() if key != "transaction_count"})
        balance_on_date = calculate_account_balance_minor(
            account.opening_balance_minor,
            **{key: value for key, value in cumulative_metrics.items() if key != "transaction_count"},
        )
        all_accounts = await self.list_accounts(include_archived=True)
        account_payload = next(item for item in all_accounts if item["id"] == str(public_id))
        return {
            "account": account_payload,
            "date": selected_date.isoformat(),
            "balance_on_date_minor": balance_on_date,
            "balance_on_date_yuan": minor_to_yuan(balance_on_date),
            "day_summary": {
                **day_metrics,
                "income_yuan": minor_to_yuan(day_metrics["income_minor"]),
                "expense_yuan": minor_to_yuan(day_metrics["expense_minor"]),
                "refund_yuan": minor_to_yuan(day_metrics["refund_minor"]),
                "transfer_in_yuan": minor_to_yuan(day_metrics["transfer_in_minor"]),
                "transfer_out_yuan": minor_to_yuan(day_metrics["transfer_out_minor"]),
                "net_change_minor": day_change,
                "net_change_yuan": minor_to_yuan(day_change),
            },
        }

    async def create_account(
        self,
        name: str,
        account_type: str,
        opening_balance_minor: int = 0,
        currency: str = "CNY",
    ) -> dict:
        await self.ensure_defaults()
        account = FinanceAccount(
            workspace_id=self.workspace_id,
            name=" ".join(name.split()).strip(),
            account_type=account_type,
            opening_balance_minor=opening_balance_minor,
            currency=currency,
        )
        self.session.add(account)
        await self.session.flush()
        self.core._changed("finance.account_created", "finance_account", str(account.public_id), "create_finance_account")
        return self.account_payload(account, {})

    async def update_account(self, public_id: uuid.UUID, changes: dict) -> dict:
        account = await self.session.scalar(
            select(FinanceAccount).where(
                FinanceAccount.workspace_id == self.workspace_id,
                FinanceAccount.public_id == public_id,
            )
        )
        if account is None:
            raise KeyError(str(public_id))
        if changes.get("name") is not None:
            cleaned = " ".join(changes["name"].split()).strip()
            duplicate = await self.session.scalar(
                select(FinanceAccount.id).where(
                    FinanceAccount.workspace_id == self.workspace_id,
                    FinanceAccount.name == cleaned,
                    FinanceAccount.id != account.id,
                )
            )
            if duplicate is not None:
                raise ValueError("这个账户已经存在")
            account.name = cleaned
        if changes.get("opening_balance_yuan") is not None:
            account.opening_balance_minor = yuan_to_minor(changes["opening_balance_yuan"])
        for key in ("account_type", "status"):
            if key in changes and changes[key] is not None:
                setattr(account, key, changes[key])
        account.updated_at = datetime.now(timezone.utc)
        self.core._changed(
            "finance.account_updated",
            "finance_account",
            str(account.public_id),
            "update_finance_account",
        )
        await self.session.flush()
        return self.account_payload(account)

    async def _category(self, public_id: uuid.UUID | None) -> FinanceCategory | None:
        if public_id is None:
            return None
        category = await self.session.scalar(
            select(FinanceCategory).where(
                FinanceCategory.workspace_id == self.workspace_id,
                FinanceCategory.public_id == public_id,
                FinanceCategory.active.is_(True),
            )
        )
        if category is None:
            raise ValueError("收支分类不存在或已停用")
        return category

    async def _account(self, public_id: uuid.UUID | None) -> FinanceAccount | None:
        if public_id is None:
            return None
        account = await self.session.scalar(
            select(FinanceAccount).where(
                FinanceAccount.workspace_id == self.workspace_id,
                FinanceAccount.public_id == public_id,
                FinanceAccount.status == "active",
            )
        )
        if account is None:
            raise ValueError("账户不存在或已停用")
        return account

    async def _transaction(self, public_id: uuid.UUID, include_deleted: bool = False) -> FinanceTransaction:
        statement = select(FinanceTransaction).where(
            FinanceTransaction.workspace_id == self.workspace_id,
            FinanceTransaction.public_id == public_id,
        )
        if not include_deleted:
            statement = statement.where(FinanceTransaction.deleted_at.is_(None))
        transaction = await self.session.scalar(statement)
        if transaction is None:
            raise KeyError(str(public_id))
        return transaction

    async def _mark_month_stale(self, target_date: date) -> None:
        month = _month_start(target_date)
        statement = (
            insert(FinanceMonthlySummary)
            .values(workspace_id=self.workspace_id, month_start=month, stale=True)
            .on_conflict_do_update(
                constraint="finance_monthly_summaries_workspace_month_key",
                set_={"stale": True, "updated_at": datetime.now(timezone.utc)},
            )
        )
        await self.session.execute(statement)

    async def _reference_maps(
        self,
        refund_transaction_ids: set[int] | None = None,
    ) -> tuple[dict[int, FinanceCategory], dict[int, FinanceAccount], dict[int, uuid.UUID]]:
        categories = list((await self.session.scalars(select(FinanceCategory).where(FinanceCategory.workspace_id == self.workspace_id))).all())
        accounts = list((await self.session.scalars(select(FinanceAccount).where(FinanceAccount.workspace_id == self.workspace_id))).all())
        transactions = []
        if refund_transaction_ids:
            transactions = list(
                (
                    await self.session.execute(
                        select(FinanceTransaction.id, FinanceTransaction.public_id).where(
                            FinanceTransaction.workspace_id == self.workspace_id,
                            FinanceTransaction.id.in_(refund_transaction_ids),
                        )
                    )
                ).all()
            )
        return (
            {item.id: item for item in categories},
            {item.id: item for item in accounts},
            {internal_id: public_id for internal_id, public_id in transactions},
        )

    @staticmethod
    def transaction_payload(
        transaction: FinanceTransaction,
        categories: dict[int, FinanceCategory],
        accounts: dict[int, FinanceAccount],
        transaction_public_ids: dict[int, uuid.UUID],
    ) -> dict:
        category = categories.get(transaction.category_id) if transaction.category_id else None
        account = accounts.get(transaction.account_id) if transaction.account_id else None
        to_account = accounts.get(transaction.to_account_id) if transaction.to_account_id else None
        return {
            "id": str(transaction.public_id),
            "type": transaction.transaction_type,
            "amount_minor": transaction.amount_minor,
            "amount_yuan": minor_to_yuan(transaction.amount_minor),
            "currency": transaction.currency,
            "occurred_at": transaction.occurred_at.isoformat(),
            "local_date": transaction.local_date.isoformat(),
            "category": FinanceRepository.category_payload(category) if category else None,
            "account": FinanceRepository.account_payload(account) if account else None,
            "to_account": FinanceRepository.account_payload(to_account) if to_account else None,
            "refund_of_id": (
                str(transaction_public_ids[transaction.refund_of_id])
                if transaction.refund_of_id in transaction_public_ids
                else None
            ),
            "merchant": transaction.merchant,
            "purpose": transaction.purpose,
            "note": transaction.note,
            "tags": list(transaction.tags),
            "source": transaction.source,
            "is_fixed": transaction.is_fixed,
            "is_necessary": transaction.is_necessary,
            "deleted": transaction.deleted_at is not None,
            "created_at": transaction.created_at.isoformat(),
            "updated_at": transaction.updated_at.isoformat(),
        }

    async def create_transaction(
        self,
        *,
        transaction_type: str,
        amount_minor: int,
        occurred_at: datetime | None,
        local_date: date | None,
        category_public_id: uuid.UUID | None,
        account_public_id: uuid.UUID | None,
        to_account_public_id: uuid.UUID | None,
        refund_of_public_id: uuid.UUID | None,
        merchant: str,
        purpose: str,
        note: str,
        tags: list[str],
        is_fixed: bool,
        is_necessary: bool,
        currency: str,
        idempotency_key: str,
        source: str,
    ) -> dict:
        await self.ensure_defaults()
        existing = await self.session.scalar(
            select(FinanceTransaction).where(
                FinanceTransaction.workspace_id == self.workspace_id,
                FinanceTransaction.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            categories, accounts, transaction_ids = await self._reference_maps(
                {existing.refund_of_id} if existing.refund_of_id else None
            )
            return self.transaction_payload(existing, categories, accounts, transaction_ids)
        if amount_minor <= 0:
            raise ValueError("金额必须大于零")

        category = await self._category(category_public_id)
        account = await self._account(account_public_id)
        to_account = await self._account(to_account_public_id)
        refund_of = await self._transaction(refund_of_public_id) if refund_of_public_id else None
        if transaction_type in {"income", "expense"}:
            if category is None or category.category_type != transaction_type:
                raise ValueError("分类类型与收入或支出不一致")
            if source == "user" and account is None:
                raise ValueError("请为这笔收支选择实际扣款或入账账户")
        if transaction_type == "transfer":
            if account is None or to_account is None or account.id == to_account.id:
                raise ValueError("转账账户无效")
            category = None
        if transaction_type == "refund":
            if refund_of is None or refund_of.transaction_type != "expense":
                raise ValueError("退款必须关联一笔有效支出")
            previous_refunds = list(
                (
                    await self.session.scalars(
                        select(FinanceTransaction.amount_minor).where(
                            FinanceTransaction.workspace_id == self.workspace_id,
                            FinanceTransaction.transaction_type == "refund",
                            FinanceTransaction.refund_of_id == refund_of.id,
                            FinanceTransaction.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
            if sum(previous_refunds) + amount_minor > refund_of.amount_minor:
                raise ValueError("累计退款金额不能超过原支出")
            category = await self.session.get(FinanceCategory, refund_of.category_id) if refund_of.category_id else None
            account = await self.session.get(FinanceAccount, refund_of.account_id) if refund_of.account_id else account

        zone = ZoneInfo(self.timezone_name)
        instant = occurred_at or datetime.now(zone)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=zone)
        day = local_date or instant.astimezone(zone).date()
        transaction = FinanceTransaction(
            workspace_id=self.workspace_id,
            idempotency_key=idempotency_key[:160],
            transaction_type=transaction_type,
            amount_minor=amount_minor,
            currency=currency,
            occurred_at=instant,
            local_date=day,
            category_id=category.id if category else None,
            account_id=account.id if account else None,
            to_account_id=to_account.id if to_account else None,
            refund_of_id=refund_of.id if refund_of else None,
            merchant=merchant.strip(),
            purpose=purpose.strip(),
            note=note.strip(),
            tags=tags,
            source=source,
            is_fixed=is_fixed,
            is_necessary=is_necessary,
        )
        self.session.add(transaction)
        await self.session.flush()
        await self._mark_month_stale(day)
        await enqueue_job(
            self.session,
            self.workspace_id,
            "finance_transaction_review",
            "finance_transaction",
            str(transaction.public_id),
            f"分析 {day.isoformat()} 的新财务记录",
            f"finance-review:{transaction.public_id}",
            {"transaction_id": str(transaction.public_id), "local_date": day.isoformat()},
        )
        self.core._changed(
            "finance.transaction_created",
            "finance_transaction",
            str(transaction.public_id),
            "create_finance_transaction",
            {"type": transaction_type, "local_date": day.isoformat()},
        )
        await self.refresh_monthly_summary(day)
        categories, accounts, transaction_ids = await self._reference_maps(
            {transaction.refund_of_id} if transaction.refund_of_id else None
        )
        return self.transaction_payload(transaction, categories, accounts, transaction_ids)

    async def get_transaction(self, public_id: uuid.UUID, include_deleted: bool = False) -> dict:
        transaction = await self._transaction(public_id, include_deleted)
        categories, accounts, transaction_ids = await self._reference_maps(
            {transaction.refund_of_id} if transaction.refund_of_id else None
        )
        return self.transaction_payload(transaction, categories, accounts, transaction_ids)

    async def list_transactions(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        transaction_type: str | None = None,
        category_public_id: uuid.UUID | None = None,
        search: str | None = None,
        account_public_id: uuid.UUID | None = None,
        include_deleted: bool = False,
        cursor: str | None = None,
        limit: int = 30,
        page: int | None = None,
    ) -> dict:
        await self.ensure_defaults()
        statement = select(FinanceTransaction).where(FinanceTransaction.workspace_id == self.workspace_id)
        if not include_deleted:
            statement = statement.where(FinanceTransaction.deleted_at.is_(None))
        if start_date:
            statement = statement.where(FinanceTransaction.local_date >= start_date)
        if end_date:
            statement = statement.where(FinanceTransaction.local_date <= end_date)
        if transaction_type:
            statement = statement.where(FinanceTransaction.transaction_type == transaction_type)
        if category_public_id:
            category = await self._category(category_public_id)
            statement = statement.where(FinanceTransaction.category_id == category.id)
        if account_public_id:
            account = await self._account(account_public_id)
            statement = statement.where(
                or_(
                    FinanceTransaction.account_id == account.id,
                    FinanceTransaction.to_account_id == account.id,
                )
            )
        if search and search.strip():
            query = search.strip()
            statement = statement.where(
                or_(
                    FinanceTransaction.merchant.icontains(query, autoescape=True),
                    FinanceTransaction.purpose.icontains(query, autoescape=True),
                    FinanceTransaction.note.icontains(query, autoescape=True),
                )
            )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        if page is not None and cursor:
            raise ValueError("页码分页和游标分页不能同时使用")
        if cursor:
            cursor_time, cursor_id = _cursor_decode(cursor)
            statement = statement.where(
                or_(
                    FinanceTransaction.occurred_at < cursor_time,
                    and_(FinanceTransaction.occurred_at == cursor_time, FinanceTransaction.id < cursor_id),
                )
            )
        ordered = statement.order_by(FinanceTransaction.occurred_at.desc(), FinanceTransaction.id.desc())
        if page is not None:
            rows = list((await self.session.scalars(ordered.offset((page - 1) * limit).limit(limit))).all())
            has_more = page * limit < total
        else:
            rows = list((await self.session.scalars(ordered.limit(limit + 1))).all())
            has_more = len(rows) > limit
            rows = rows[:limit]
        categories, accounts, transaction_ids = await self._reference_maps(
            {item.refund_of_id for item in rows if item.refund_of_id is not None}
        )
        return {
            "items": [
                self.transaction_payload(item, categories, accounts, transaction_ids)
                for item in rows
            ],
            "next_cursor": _cursor_encode(rows[-1].occurred_at, rows[-1].id) if has_more and rows else None,
            "page": page,
            "page_size": limit,
            "total": total,
            "total_pages": max(1, (total + limit - 1) // limit),
        }

    async def update_transaction(self, public_id: uuid.UUID, changes: dict) -> dict:
        transaction = await self._transaction(public_id)
        old_date = transaction.local_date
        if changes.get("amount_yuan") is not None:
            transaction.amount_minor = yuan_to_minor(changes["amount_yuan"])
        if changes.get("occurred_at") is not None:
            instant = changes["occurred_at"]
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=ZoneInfo(self.timezone_name))
            transaction.occurred_at = instant
            if changes.get("local_date") is None:
                transaction.local_date = instant.astimezone(ZoneInfo(self.timezone_name)).date()
        if changes.get("local_date") is not None:
            transaction.local_date = changes["local_date"]
        if "category_id" in changes and changes["category_id"] is not None:
            category = await self._category(changes["category_id"])
            expected = "expense" if transaction.transaction_type in {"expense", "refund"} else "income"
            if category.category_type != expected:
                raise ValueError("分类类型与这笔记录不一致")
            transaction.category_id = category.id
        if "account_id" in changes and changes["account_id"] is not None:
            account = await self._account(changes["account_id"])
            transaction.account_id = account.id
        for key in ("merchant", "purpose", "note", "tags", "is_fixed", "is_necessary"):
            if key in changes and changes[key] is not None:
                setattr(transaction, key, changes[key].strip() if isinstance(changes[key], str) else changes[key])
        transaction.updated_at = datetime.now(timezone.utc)
        await self._mark_month_stale(old_date)
        await self._mark_month_stale(transaction.local_date)
        self.core._changed("finance.transaction_updated", "finance_transaction", str(public_id), "update_finance_transaction")
        await self.session.flush()
        await self.refresh_monthly_summary(old_date)
        if _month_start(transaction.local_date) != _month_start(old_date):
            await self.refresh_monthly_summary(transaction.local_date)
        return await self.get_transaction(public_id)

    async def set_deleted(self, public_id: uuid.UUID, deleted: bool) -> dict:
        transaction = await self._transaction(public_id, include_deleted=True)
        transaction.deleted_at = datetime.now(timezone.utc) if deleted else None
        transaction.updated_at = datetime.now(timezone.utc)
        await self._mark_month_stale(transaction.local_date)
        self.core._changed(
            "finance.transaction_deleted" if deleted else "finance.transaction_restored",
            "finance_transaction",
            str(public_id),
            "delete_finance_transaction" if deleted else "restore_finance_transaction",
        )
        await self.session.flush()
        await self.refresh_monthly_summary(transaction.local_date)
        return await self.get_transaction(public_id, include_deleted=True)

    async def refresh_monthly_summary(self, target_date: date) -> dict:
        month = _month_start(target_date)
        result = await self.summary(month, _month_end(month))
        row = await self.session.scalar(
            select(FinanceMonthlySummary).where(
                FinanceMonthlySummary.workspace_id == self.workspace_id,
                FinanceMonthlySummary.month_start == month,
            )
        )
        if row is None:
            row = FinanceMonthlySummary(
                workspace_id=self.workspace_id,
                month_start=month,
                revision=1,
            )
            self.session.add(row)
        else:
            row.revision = (row.revision or 0) + 1
        row.income_minor = result["income_minor"]
        row.expense_minor = result["expense_minor"]
        row.refund_minor = result["refund_minor"]
        row.net_minor = result["net_minor"]
        row.savings_rate = (
            Decimal(str(result["savings_rate"])) if result["savings_rate"] is not None else None
        )
        row.category_breakdown = {
            item["category"]["id"]: {
                "name": item["category"]["name"],
                "amount_minor": item["amount_minor"],
                "share": item["share"],
            }
            for item in result["category_breakdown"]
        }
        row.budget_status = {item["id"]: item for item in result["budgets"]}
        row.stale = False
        row.generated_at = datetime.now(timezone.utc)
        row.updated_at = row.generated_at
        await self.session.flush()
        return result

    async def summary(self, start_date: date, end_date: date) -> dict:
        if end_date < start_date:
            raise ValueError("结束日期不能早于开始日期")
        if (end_date - start_date).days > 3660:
            raise ValueError("单次统计周期不能超过十年")
        conditions = (
            FinanceTransaction.workspace_id == self.workspace_id,
            FinanceTransaction.local_date.between(start_date, end_date),
            FinanceTransaction.deleted_at.is_(None),
        )
        aggregate = (
            await self.session.execute(
                select(
                    func.count(FinanceTransaction.id).label("transaction_count"),
                    func.coalesce(
                        func.sum(FinanceTransaction.amount_minor).filter(
                            FinanceTransaction.transaction_type == "income"
                        ),
                        0,
                    ).label("income"),
                    func.coalesce(
                        func.sum(FinanceTransaction.amount_minor).filter(
                            FinanceTransaction.transaction_type == "expense"
                        ),
                        0,
                    ).label("expense"),
                    func.coalesce(
                        func.sum(FinanceTransaction.amount_minor).filter(
                            FinanceTransaction.transaction_type == "refund"
                        ),
                        0,
                    ).label("refund"),
                    func.coalesce(
                        func.sum(FinanceTransaction.amount_minor).filter(
                            FinanceTransaction.transaction_type == "transfer"
                        ),
                        0,
                    ).label("transfer"),
                    func.count(FinanceTransaction.id).filter(
                        FinanceTransaction.account_id.is_(None),
                        FinanceTransaction.transaction_type.in_(("income", "expense", "refund")),
                    ).label("unassigned_transaction_count"),
                ).where(*conditions)
            )
        ).one()
        categories, _, _ = await self._reference_maps()
        totals = {
            "income": int(aggregate.income or 0),
            "expense": int(aggregate.expense or 0),
            "refund": int(aggregate.refund or 0),
            "transfer": int(aggregate.transfer or 0),
        }
        category_rows = list(
            (
                await self.session.execute(
                    select(
                        FinanceTransaction.category_id,
                        (
                            func.coalesce(
                                func.sum(FinanceTransaction.amount_minor).filter(
                                    FinanceTransaction.transaction_type == "expense"
                                ),
                                0,
                            )
                            - func.coalesce(
                                func.sum(FinanceTransaction.amount_minor).filter(
                                    FinanceTransaction.transaction_type == "refund"
                                ),
                                0,
                            )
                        ).label("amount"),
                    )
                    .where(
                        *conditions,
                        FinanceTransaction.category_id.is_not(None),
                        FinanceTransaction.transaction_type.in_(("expense", "refund")),
                    )
                    .group_by(FinanceTransaction.category_id)
                )
            ).all()
        )
        category_totals = {int(item.category_id): int(item.amount or 0) for item in category_rows}
        month_key = func.to_char(FinanceTransaction.local_date, "YYYY-MM")
        month_rows = list(
            (
                await self.session.execute(
                    select(
                        month_key.label("month"),
                        func.coalesce(
                            func.sum(FinanceTransaction.amount_minor).filter(
                                FinanceTransaction.transaction_type == "income"
                            ),
                            0,
                        ).label("income"),
                        func.coalesce(
                            func.sum(FinanceTransaction.amount_minor).filter(
                                FinanceTransaction.transaction_type == "expense"
                            ),
                            0,
                        ).label("expense"),
                        func.coalesce(
                            func.sum(FinanceTransaction.amount_minor).filter(
                                FinanceTransaction.transaction_type == "refund"
                            ),
                            0,
                        ).label("refund"),
                    )
                    .where(*conditions)
                    .group_by(month_key)
                    .order_by(month_key)
                )
            ).all()
        )
        month_totals = {
            item.month: {
                "income": int(item.income or 0),
                "expense": int(item.expense or 0),
                "refund": int(item.refund or 0),
                "net": int(item.income or 0) - int(item.expense or 0) + int(item.refund or 0),
            }
            for item in month_rows
        }
        net = totals["income"] - totals["expense"] + totals["refund"]
        breakdown = []
        for category_id, amount in sorted(category_totals.items(), key=lambda item: item[1], reverse=True):
            category = categories.get(category_id)
            if category is None:
                continue
            breakdown.append(
                {
                    "category": self.category_payload(category),
                    "amount_minor": amount,
                    "amount_yuan": minor_to_yuan(amount),
                    "share": round(amount / max(totals["expense"] - totals["refund"], 1), 4),
                }
            )
        budgets = list(
            (
                await self.session.scalars(
                    select(FinanceBudget).where(
                        FinanceBudget.workspace_id == self.workspace_id,
                        FinanceBudget.status == "active",
                        FinanceBudget.period_start <= end_date,
                        FinanceBudget.period_end >= start_date,
                    )
                )
            ).all()
        )
        budget_items = []
        for budget in budgets:
            spent = (
                sum(category_totals.values())
                if budget.category_id is None
                else category_totals.get(budget.category_id, 0)
            )
            budget_items.append(
                {
                    "id": str(budget.public_id),
                    "category": self.category_payload(categories[budget.category_id]) if budget.category_id in categories else None,
                    "period_start": budget.period_start.isoformat(),
                    "period_end": budget.period_end.isoformat(),
                    "amount_minor": budget.amount_minor,
                    "amount_yuan": minor_to_yuan(budget.amount_minor),
                    "spent_minor": spent,
                    "spent_yuan": minor_to_yuan(spent),
                    "progress": round(spent / budget.amount_minor, 4),
                    "over_budget": spent > budget.amount_minor,
                }
            )
        effective_expense = totals["expense"] - totals["refund"]
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "currency": "CNY",
            "income_minor": totals["income"],
            "income_yuan": minor_to_yuan(totals["income"]),
            "expense_minor": effective_expense,
            "expense_yuan": minor_to_yuan(effective_expense),
            "refund_minor": totals["refund"],
            "refund_yuan": minor_to_yuan(totals["refund"]),
            "net_minor": net,
            "net_yuan": minor_to_yuan(net),
            "savings_rate": round(net / totals["income"], 4) if totals["income"] else None,
            "category_breakdown": breakdown,
            "timeline": [
                {"month": month, **values, **{f"{key}_yuan": minor_to_yuan(value) for key, value in values.items()}}
                for month, values in sorted(month_totals.items())
            ],
            "budgets": budget_items,
            "transaction_count": int(aggregate.transaction_count or 0),
            "unassigned_transaction_count": int(aggregate.unassigned_transaction_count or 0),
        }

    async def archive(self, start_month: date, end_month: date) -> list[dict]:
        start = _month_start(start_month)
        end = _month_start(end_month)
        if end < start:
            raise ValueError("归档结束月份不能早于开始月份")
        end_day = date(end.year + (1 if end.month == 12 else 0), 1 if end.month == 12 else end.month + 1, 1)
        result = await self.summary(start, date.fromordinal(end_day.toordinal() - 1))
        return list(reversed(result["timeline"]))

    @staticmethod
    def recurring_payload(
        rule: FinanceRecurringRule,
        categories: dict[int, FinanceCategory],
        accounts: dict[int, FinanceAccount],
    ) -> dict:
        category = categories.get(rule.category_id) if rule.category_id else None
        account = accounts.get(rule.account_id) if rule.account_id else None
        to_account = accounts.get(rule.to_account_id) if rule.to_account_id else None
        return {
            "id": str(rule.public_id),
            "name": rule.name,
            "transaction_type": rule.transaction_type,
            "amount_minor": rule.amount_minor,
            "amount_yuan": minor_to_yuan(rule.amount_minor),
            "currency": rule.currency,
            "category": FinanceRepository.category_payload(category) if category else None,
            "account": FinanceRepository.account_payload(account) if account else None,
            "to_account": FinanceRepository.account_payload(to_account) if to_account else None,
            "frequency": rule.frequency,
            "interval_count": rule.interval_count,
            "next_due_date": rule.next_due_date.isoformat(),
            "purpose": rule.purpose,
            "active": rule.active,
        }

    async def list_recurring_rules(self, include_inactive: bool = False) -> list[dict]:
        statement = select(FinanceRecurringRule).where(
            FinanceRecurringRule.workspace_id == self.workspace_id
        )
        if not include_inactive:
            statement = statement.where(FinanceRecurringRule.active.is_(True))
        rules = list(
            (
                await self.session.scalars(
                    statement.order_by(FinanceRecurringRule.next_due_date, FinanceRecurringRule.id)
                )
            ).all()
        )
        categories, accounts, _ = await self._reference_maps()
        return [self.recurring_payload(item, categories, accounts) for item in rules]

    async def create_recurring_rule(
        self,
        *,
        name: str,
        transaction_type: str,
        amount_minor: int,
        category_public_id: uuid.UUID | None,
        account_public_id: uuid.UUID | None,
        to_account_public_id: uuid.UUID | None,
        frequency: str,
        interval_count: int,
        next_due_date: date,
        purpose: str,
        currency: str,
    ) -> dict:
        category = await self._category(category_public_id)
        account = await self._account(account_public_id)
        to_account = await self._account(to_account_public_id)
        if transaction_type in {"income", "expense"}:
            if category is None or category.category_type != transaction_type:
                raise ValueError("周期规则的分类与收支类型不一致")
        elif account is None or to_account is None or account.id == to_account.id:
            raise ValueError("周期转账账户无效")
        rule = FinanceRecurringRule(
            workspace_id=self.workspace_id,
            name=" ".join(name.split()).strip(),
            transaction_type=transaction_type,
            amount_minor=amount_minor,
            currency=currency,
            category_id=category.id if category else None,
            account_id=account.id if account else None,
            to_account_id=to_account.id if to_account else None,
            frequency=frequency,
            interval_count=interval_count,
            next_due_date=next_due_date,
            purpose=purpose.strip(),
        )
        self.session.add(rule)
        await self.session.flush()
        self.core._changed("finance.recurring_rule_created", "finance_recurring_rule", str(rule.public_id), "create_finance_recurring_rule")
        categories, accounts, _ = await self._reference_maps()
        return self.recurring_payload(rule, categories, accounts)

    async def update_recurring_rule(self, public_id: uuid.UUID, changes: dict) -> dict:
        rule = await self.session.scalar(
            select(FinanceRecurringRule).where(
                FinanceRecurringRule.workspace_id == self.workspace_id,
                FinanceRecurringRule.public_id == public_id,
            )
        )
        if rule is None:
            raise KeyError(str(public_id))
        if changes.get("amount_yuan") is not None:
            rule.amount_minor = yuan_to_minor(changes.pop("amount_yuan"))
        for key, value in changes.items():
            if value is not None:
                setattr(rule, key, value.strip() if isinstance(value, str) else value)
        rule.updated_at = datetime.now(timezone.utc)
        self.core._changed("finance.recurring_rule_updated", "finance_recurring_rule", str(rule.public_id), "update_finance_recurring_rule")
        await self.session.flush()
        categories, accounts, _ = await self._reference_maps()
        return self.recurring_payload(rule, categories, accounts)

    @staticmethod
    def _advance_due_date(value: date, frequency: str, interval_count: int) -> date:
        if frequency == "weekly":
            return value + timedelta(days=7 * interval_count)
        if frequency == "yearly":
            target_year = value.year + interval_count
            return value.replace(year=target_year, day=min(value.day, calendar.monthrange(target_year, value.month)[1]))
        total_months = value.year * 12 + value.month - 1 + interval_count
        target_year, month_index = divmod(total_months, 12)
        target_month = month_index + 1
        return date(target_year, target_month, min(value.day, calendar.monthrange(target_year, target_month)[1]))

    async def process_due_recurring_rules(self, today: date, limit: int = 50) -> int:
        rules = list(
            (
                await self.session.scalars(
                    select(FinanceRecurringRule)
                    .where(
                        FinanceRecurringRule.workspace_id == self.workspace_id,
                        FinanceRecurringRule.active.is_(True),
                        FinanceRecurringRule.next_due_date <= today,
                    )
                    .order_by(FinanceRecurringRule.next_due_date, FinanceRecurringRule.id)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).all()
        )
        created = 0
        for rule in rules:
            category = await self.session.get(FinanceCategory, rule.category_id) if rule.category_id else None
            account = await self.session.get(FinanceAccount, rule.account_id) if rule.account_id else None
            to_account = await self.session.get(FinanceAccount, rule.to_account_id) if rule.to_account_id else None
            due_date = rule.next_due_date
            await self.create_transaction(
                transaction_type=rule.transaction_type,
                amount_minor=rule.amount_minor,
                occurred_at=datetime.combine(due_date, time(hour=9), tzinfo=ZoneInfo(self.timezone_name)),
                local_date=due_date,
                category_public_id=category.public_id if category else None,
                account_public_id=account.public_id if account else None,
                to_account_public_id=to_account.public_id if to_account else None,
                refund_of_public_id=None,
                merchant="",
                purpose=rule.purpose or rule.name,
                note=f"由周期规则“{rule.name}”自动生成",
                tags=["周期记账"],
                is_fixed=True,
                is_necessary=False,
                currency=rule.currency,
                idempotency_key=f"recurring:{rule.public_id}:{due_date.isoformat()}",
                source="system",
            )
            rule.next_due_date = self._advance_due_date(due_date, rule.frequency, rule.interval_count)
            rule.updated_at = datetime.now(timezone.utc)
            created += 1
        return created

    async def upsert_budget(
        self,
        *,
        period_start: date,
        period_end: date,
        amount_minor: int,
        category_public_id: uuid.UUID | None,
        currency: str,
        rollover: bool,
    ) -> dict:
        category = await self._category(category_public_id)
        if category is not None and category.category_type != "expense":
            raise ValueError("预算只能使用支出分类")
        statement = select(FinanceBudget).where(
            FinanceBudget.workspace_id == self.workspace_id,
            FinanceBudget.period_start == period_start,
            FinanceBudget.period_end == period_end,
        )
        statement = statement.where(
            FinanceBudget.category_id == category.id if category else FinanceBudget.category_id.is_(None)
        )
        budget = await self.session.scalar(statement)
        if budget is None:
            budget = FinanceBudget(
                workspace_id=self.workspace_id,
                category_id=category.id if category else None,
                period_start=period_start,
                period_end=period_end,
                amount_minor=amount_minor,
                currency=currency,
                rollover=rollover,
            )
            self.session.add(budget)
        else:
            budget.amount_minor = amount_minor
            budget.rollover = rollover
            budget.status = "active"
            budget.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        self.core._changed("finance.budget_updated", "finance_budget", str(budget.public_id), "upsert_finance_budget")
        current_month = _month_start(period_start)
        final_month = _month_start(period_end)
        while current_month <= final_month:
            await self.refresh_monthly_summary(current_month)
            current_month = _next_month(current_month)
        return {
            "id": str(budget.public_id),
            "period_start": budget.period_start.isoformat(),
            "period_end": budget.period_end.isoformat(),
            "amount_minor": budget.amount_minor,
            "amount_yuan": minor_to_yuan(budget.amount_minor),
            "category": self.category_payload(category) if category else None,
            "rollover": budget.rollover,
            "status": budget.status,
        }

    async def list_budgets(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        include_archived: bool = False,
    ) -> list[dict]:
        statement = select(FinanceBudget).where(
            FinanceBudget.workspace_id == self.workspace_id
        )
        if not include_archived:
            statement = statement.where(FinanceBudget.status == "active")
        if start_date is not None:
            statement = statement.where(FinanceBudget.period_end >= start_date)
        if end_date is not None:
            statement = statement.where(FinanceBudget.period_start <= end_date)
        budgets = list(
            (
                await self.session.scalars(
                    statement.order_by(
                        FinanceBudget.period_start.desc(),
                        FinanceBudget.id.desc(),
                    )
                )
            ).all()
        )
        categories, _, _ = await self._reference_maps()
        return [
            {
                "id": str(item.public_id),
                "period_start": item.period_start.isoformat(),
                "period_end": item.period_end.isoformat(),
                "amount_minor": item.amount_minor,
                "amount_yuan": minor_to_yuan(item.amount_minor),
                "currency": item.currency,
                "category": (
                    self.category_payload(categories[item.category_id])
                    if item.category_id in categories
                    else None
                ),
                "rollover": item.rollover,
                "status": item.status,
            }
            for item in budgets
        ]

    async def delete_budget(self, public_id: uuid.UUID) -> dict:
        budget = await self.session.scalar(
            select(FinanceBudget).where(
                FinanceBudget.workspace_id == self.workspace_id,
                FinanceBudget.public_id == public_id,
            )
        )
        if budget is None:
            raise KeyError(str(public_id))
        budget.status = "archived"
        budget.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        self.core._changed(
            "finance.budget_deleted",
            "finance_budget",
            str(budget.public_id),
            "delete_finance_budget",
        )
        current_month = _month_start(budget.period_start)
        final_month = _month_start(budget.period_end)
        while current_month <= final_month:
            await self.refresh_monthly_summary(current_month)
            current_month = _next_month(current_month)
        return {
            "id": str(budget.public_id),
            "deleted": True,
            "period_start": budget.period_start.isoformat(),
            "period_end": budget.period_end.isoformat(),
        }

    @staticmethod
    def goal_payload(goal: SavingsGoal) -> dict:
        return {
            "id": str(goal.public_id),
            "name": goal.name,
            "target_amount_minor": goal.target_amount_minor,
            "target_amount_yuan": minor_to_yuan(goal.target_amount_minor),
            "current_amount_minor": goal.current_amount_minor,
            "current_amount_yuan": minor_to_yuan(goal.current_amount_minor),
            "progress": round(goal.current_amount_minor / goal.target_amount_minor, 4),
            "currency": goal.currency,
            "target_date": goal.target_date.isoformat() if goal.target_date else None,
            "status": goal.status,
        }

    async def list_goals(self) -> list[dict]:
        goals = list(
            (
                await self.session.scalars(
                    select(SavingsGoal)
                    .where(SavingsGoal.workspace_id == self.workspace_id)
                    .order_by(SavingsGoal.status != "active", SavingsGoal.target_date, SavingsGoal.id)
                )
            ).all()
        )
        return [self.goal_payload(item) for item in goals]

    async def create_goal(
        self,
        name: str,
        target_amount_minor: int,
        current_amount_minor: int,
        target_date: date | None,
        currency: str,
    ) -> dict:
        goal = SavingsGoal(
            workspace_id=self.workspace_id,
            name=" ".join(name.split()).strip(),
            target_amount_minor=target_amount_minor,
            current_amount_minor=current_amount_minor,
            target_date=target_date,
            currency=currency,
        )
        self.session.add(goal)
        await self.session.flush()
        self.core._changed("finance.savings_goal_created", "savings_goal", str(goal.public_id), "create_savings_goal")
        return self.goal_payload(goal)

    async def update_goal(self, public_id: uuid.UUID, changes: dict) -> dict:
        goal = await self.session.scalar(
            select(SavingsGoal).where(
                SavingsGoal.workspace_id == self.workspace_id,
                SavingsGoal.public_id == public_id,
            )
        )
        if goal is None:
            raise KeyError(str(public_id))
        amount_fields = {
            "target_amount_yuan": "target_amount_minor",
            "current_amount_yuan": "current_amount_minor",
        }
        for key, value in changes.items():
            if value is None:
                continue
            if key in amount_fields:
                setattr(goal, amount_fields[key], yuan_to_minor(value))
            else:
                setattr(goal, key, value.strip() if isinstance(value, str) else value)
        goal.updated_at = datetime.now(timezone.utc)
        self.core._changed("finance.savings_goal_updated", "savings_goal", str(goal.public_id), "update_savings_goal")
        await self.session.flush()
        return self.goal_payload(goal)

    async def save_insight(
        self,
        *,
        period_start: date,
        period_end: date,
        finding: str,
        evidence: str,
        risk: str,
        action: str,
        next_goal: str,
        source: str,
    ) -> dict:
        insight = FinanceInsight(
            workspace_id=self.workspace_id,
            period_start=period_start,
            period_end=period_end,
            finding=finding.strip(),
            evidence=evidence.strip(),
            risk=risk.strip(),
            action=action.strip(),
            next_goal=next_goal.strip(),
            source=source,
        )
        self.session.add(insight)
        await self.session.flush()
        self.core._changed("finance.insight_created", "finance_insight", str(insight.public_id), "create_finance_insight")
        return self.insight_payload(insight)

    @staticmethod
    def insight_payload(insight: FinanceInsight) -> dict:
        return {
            "id": str(insight.public_id),
            "period_start": insight.period_start.isoformat(),
            "period_end": insight.period_end.isoformat(),
            "finding": insight.finding,
            "evidence": insight.evidence,
            "risk": insight.risk,
            "action": insight.action,
            "next_goal": insight.next_goal,
            "source": insight.source,
            "created_at": insight.created_at.isoformat(),
        }

    async def list_insights(self, limit: int = 12) -> list[dict]:
        items = list(
            (
                await self.session.scalars(
                    select(FinanceInsight)
                    .where(FinanceInsight.workspace_id == self.workspace_id)
                    .order_by(FinanceInsight.period_end.desc(), FinanceInsight.id.desc())
                    .limit(limit)
                )
            ).all()
        )
        return [self.insight_payload(item) for item in items]
