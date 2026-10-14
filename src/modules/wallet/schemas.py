from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Money = Annotated[int, PlainSerializer(str, return_type=str, when_used="json")]


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    driver_id: UUID
    balance_vnd: Money
    balance: Money
    currency: str = "VND"
    status: str
    is_negative: bool
    debt_amount_vnd: Money
    debt_amount: Money


class WalletLedgerItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    wallet_id: UUID
    amount_vnd: Money
    amount: Money
    balance_after_vnd: Money
    balance_after: Money
    entry_type: str
    reference_type: str
    reference_id: str
    description: str
    created_at: datetime


class WalletTransactionResponse(WalletLedgerItemResponse):
    topup_order_id: str | None = None
    topup_status: str | None = None
    topup_reason: str | None = None


class WalletLedgerListResponse(BaseModel):
    items: list[WalletLedgerItemResponse] = Field(default_factory=list)
    next_cursor: int | None = None
    has_more: bool = False
