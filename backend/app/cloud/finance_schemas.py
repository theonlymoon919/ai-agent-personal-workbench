from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


CurrencyCode = Literal["CNY"]
TransactionType = Literal["income", "expense", "transfer", "refund"]
CategoryType = Literal["income", "expense"]


def _clean_tags(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = " ".join(value.split()).strip()
        if cleaned and cleaned not in result:
            result.append(cleaned[:40])
    return result[:20]


class FinanceAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    account_type: Literal["cash", "wechat", "alipay", "bank", "other"] = "other"
    opening_balance_yuan: Decimal = Field(default=Decimal("0"), ge=Decimal("-9999999999.99"), le=Decimal("9999999999.99"))
    currency: CurrencyCode = "CNY"


class FinanceAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    account_type: Literal["cash", "wechat", "alipay", "bank", "other"] | None = None
    opening_balance_yuan: Decimal | None = Field(
        default=None,
        ge=Decimal("-9999999999.99"),
        le=Decimal("9999999999.99"),
    )
    status: Literal["active", "archived"] | None = None


class FinanceCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category_type: CategoryType
    icon: str = Field(default="", max_length=40)
    color: str = Field(default="", max_length=16)


class FinanceCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=16)
    active: bool | None = None


class FinanceTransactionCreate(BaseModel):
    transaction_type: TransactionType
    amount_yuan: Decimal = Field(gt=Decimal("0"), le=Decimal("9999999999.99"))
    currency: CurrencyCode = "CNY"
    occurred_at: datetime | None = None
    local_date: date | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    refund_of_id: uuid.UUID | None = None
    merchant: str = Field(default="", max_length=160)
    purpose: str = Field(default="", max_length=240)
    note: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    is_fixed: bool = False
    is_necessary: bool = False

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return _clean_tags(value)

    @model_validator(mode="after")
    def validate_relationships(self) -> "FinanceTransactionCreate":
        if self.transaction_type == "transfer":
            if not self.account_id or not self.to_account_id:
                raise ValueError("转账必须同时选择转出账户和转入账户")
            if self.account_id == self.to_account_id:
                raise ValueError("转出账户和转入账户不能相同")
            if self.category_id is not None:
                raise ValueError("转账不使用收支分类")
        elif self.to_account_id is not None:
            raise ValueError("只有转账可以填写转入账户")
        if self.transaction_type == "refund" and self.refund_of_id is None:
            raise ValueError("退款必须关联原支出")
        if self.transaction_type != "refund" and self.refund_of_id is not None:
            raise ValueError("只有退款可以关联原记录")
        if self.transaction_type in {"income", "expense"} and self.category_id is None:
            raise ValueError("收入和支出必须选择分类")
        return self


class FinanceTransactionUpdate(BaseModel):
    amount_yuan: Decimal | None = Field(default=None, gt=Decimal("0"), le=Decimal("9999999999.99"))
    occurred_at: datetime | None = None
    local_date: date | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    merchant: str | None = Field(default=None, max_length=160)
    purpose: str | None = Field(default=None, max_length=240)
    note: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=20)
    is_fixed: bool | None = None
    is_necessary: bool | None = None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str] | None) -> list[str] | None:
        return _clean_tags(value) if value is not None else None


class FinanceBudgetUpsert(BaseModel):
    period_start: date
    period_end: date
    amount_yuan: Decimal = Field(gt=Decimal("0"), le=Decimal("9999999999.99"))
    category_id: uuid.UUID | None = None
    currency: CurrencyCode = "CNY"
    rollover: bool = False

    @model_validator(mode="after")
    def validate_period(self) -> "FinanceBudgetUpsert":
        if self.period_end < self.period_start:
            raise ValueError("预算结束日期不能早于开始日期")
        if (self.period_end - self.period_start).days > 366:
            raise ValueError("单个预算周期不能超过一年")
        return self


class FinanceRecurringRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    transaction_type: Literal["income", "expense", "transfer"]
    amount_yuan: Decimal = Field(gt=Decimal("0"), le=Decimal("9999999999.99"))
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    frequency: Literal["weekly", "monthly", "yearly"] = "monthly"
    interval_count: int = Field(default=1, ge=1, le=60)
    next_due_date: date
    purpose: str = Field(default="", max_length=240)
    currency: CurrencyCode = "CNY"

    @model_validator(mode="after")
    def validate_relationships(self) -> "FinanceRecurringRuleCreate":
        if self.transaction_type == "transfer":
            if not self.account_id or not self.to_account_id or self.account_id == self.to_account_id:
                raise ValueError("周期转账必须选择两个不同账户")
            if self.category_id is not None:
                raise ValueError("周期转账不使用收支分类")
        elif self.category_id is None:
            raise ValueError("周期收入或支出必须选择分类")
        return self


class FinanceRecurringRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    amount_yuan: Decimal | None = Field(default=None, gt=Decimal("0"), le=Decimal("9999999999.99"))
    frequency: Literal["weekly", "monthly", "yearly"] | None = None
    interval_count: int | None = Field(default=None, ge=1, le=60)
    next_due_date: date | None = None
    purpose: str | None = Field(default=None, max_length=240)
    active: bool | None = None


class SavingsGoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    target_amount_yuan: Decimal = Field(gt=Decimal("0"), le=Decimal("9999999999.99"))
    current_amount_yuan: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("9999999999.99"))
    target_date: date | None = None
    currency: CurrencyCode = "CNY"


class SavingsGoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    target_amount_yuan: Decimal | None = Field(default=None, gt=Decimal("0"), le=Decimal("9999999999.99"))
    current_amount_yuan: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("9999999999.99"))
    target_date: date | None = None
    status: Literal["active", "completed", "paused"] | None = None


class FinanceInsightCreate(BaseModel):
    period_start: date
    period_end: date
    finding: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=2000)
    risk: str = Field(default="", max_length=2000)
    action: str = Field(min_length=1, max_length=2000)
    next_goal: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_period(self) -> "FinanceInsightCreate":
        if self.period_end < self.period_start:
            raise ValueError("建议周期无效")
        return self
