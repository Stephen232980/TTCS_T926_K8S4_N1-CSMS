from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)
from sqlalchemy import select

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    AuditEvidence,
    CurrentActorDependency,
    authorize_request,
)
from src.modules.ocpp import configuration as service
from src.modules.ocpp.configuration_models import ConfigurationIntent
from src.modules.wallet.admin_route import WalletCommandRoute
from src.modules.wallet.admin_router import Database

router = APIRouter(
    prefix="/api/v1/ops/charge-points",
    tags=["charger-configuration"],
    route_class=WalletCommandRoute,
    dependencies=[Depends(authorize_request)],
)


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    key: Literal["HeartbeatInterval", "MeterValueSampleInterval"]
    value: int = Field(strict=True)

    @model_validator(mode="after")
    def bounds(self) -> Self:
        low, high = service.LIMITS[self.key]
        if not low <= self.value <= high:
            raise ValueError(f"Giá trị phải từ {low} đến {high} giây")
        return self


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    intent_id: UUID
    confirm: Literal[True]

    @field_validator("confirm", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Cần xác nhận khởi động lại.")
        return value


class IntentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    key: str
    value: int
    old_value: str | None
    actual_value: str | None
    state: str
    outcome: str | None
    verified_at: datetime | None
    created_at: datetime
    reset_id: UUID | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reset_requested(self) -> bool:
        return self.reset_id is not None


class KeyResponse(BaseModel):
    key: str
    value: str | None
    readonly: bool
    minimum: int
    maximum: int


class ConfigurationResponse(BaseModel):
    online: bool
    outcome: str
    keys: list[KeyResponse]
    intents: list[IntentResponse]
    reset_blocked: bool


@router.get("/{point_id}/configuration", response_model=ConfigurationResponse)
@user_policy("ops.configuration.read", "all", "operator")
async def get_configuration(
    point_id: UUID, db: Database, refresh: Annotated[bool, Query()] = True
) -> ConfigurationResponse:
    point = await service.charger(db, point_id)
    conn = await service.connection_for(point)
    outcome, payload = (
        await service.read(conn, list(service.LIMITS))
        if conn and refresh
        else ("Offline" if conn is None else "Cached", None)
    )
    keys = []
    if payload:
        for key, (low, high) in service.LIMITS.items():
            item = next(
                (entry for entry in payload.configurationKey if entry.key == key), None
            )
            keys.append(
                KeyResponse(
                    key=key,
                    value=item.value if item else None,
                    readonly=item.readonly if item else True,
                    minimum=low,
                    maximum=high,
                )
            )
    rows = (
        await db.scalars(
            select(ConfigurationIntent)
            .where(ConfigurationIntent.charge_point_id == point_id)
            .order_by(ConfigurationIntent.created_at.desc())
            .limit(10)
        )
    ).all()
    return ConfigurationResponse(
        online=conn is not None,
        outcome=outcome,
        keys=keys,
        intents=[IntentResponse.model_validate(row) for row in rows],
        reset_blocked=await service.busy(db, point_id),
    )


@router.post(
    "/{point_id}/configuration", response_model=IntentResponse, status_code=202
)
@user_policy("ops.configuration.change", "all", "operator")
async def change(
    point_id: UUID,
    body: ChangeRequest,
    actor: CurrentActorDependency,
    db: Database,
    evidence: AuditEvidence,
) -> IntentResponse:
    row = await service.submit(
        db, point_id, body.request_id, actor.user_id, body.key, body.value, evidence
    )
    await db.commit()
    return IntentResponse.model_validate(row)


@router.post(
    "/{point_id}/configuration/reset", response_model=IntentResponse, status_code=202
)
@user_policy("ops.configuration.reset", "all", "operator")
async def reset(
    point_id: UUID,
    body: ResetRequest,
    actor: CurrentActorDependency,
    db: Database,
    evidence: AuditEvidence,
) -> IntentResponse:
    row = await service.request_reset(
        db, point_id, body.intent_id, body.request_id, actor.user_id, evidence
    )
    await db.commit()
    return IntentResponse.model_validate(row)
