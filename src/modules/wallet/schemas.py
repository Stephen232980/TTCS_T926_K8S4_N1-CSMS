from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    driver_id: UUID
    balance_vnd: int
    balance: int
    currency: str = "VND"
    status: str
    is_negative: bool
    debt_amount_vnd: int
    debt_amount: int


class WalletLedgerItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    wallet_id: UUID
    amount_vnd: int
    amount: int
    balance_after_vnd: int
    balance_after: int
    entry_type: str
    reference_type: str
    reference_id: str
    description: str
    created_at: datetime


class WalletLedgerListResponse(BaseModel):
    items: list[WalletLedgerItemResponse] = Field(default_factory=list)
    next_cursor: int | None = None
    has_more: bool = False
