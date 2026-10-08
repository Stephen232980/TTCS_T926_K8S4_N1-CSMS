"""Audit summaries only; detailed business payloads stay in their owning tables."""

import json
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.audit.models import AuditLog

# Normalize case and separators so idTag, id_tag and ID-Tag match equally.
SENSITIVE_KEYS = frozenset(
    {
        "idtag",
        "idtoken",
        "cardcode",
        "cardnumber",
        "cardid",
        "macard",
        "mathe",
        "email",
        "emailaddress",
        "phone",
        "phonenumber",
        "telephone",
        "sodienthoai",
        "token",
        "accesstoken",
        "refreshtoken",
        "sessiontoken",
        "authorization",
        "password",
        "passwordhash",
        "secret",
        "webhooksecret",
        "cookie",
        "fullname",
        "name",
        "address",
        "identitynumber",
        "nationalid",
        "cccd",
        "cmnd",
    }
)


def _validate_json(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError("Audit JSON keys must be strings")
            normalized = "".join(
                character for character in key.casefold() if character.isalnum()
            )
            if normalized in SENSITIVE_KEYS:
                raise ValueError("Sensitive audit JSON key is forbidden")
            _validate_json(child)
    elif isinstance(value, list):
        for child in value:
            _validate_json(child)
    elif value is not None and type(value) not in {str, int, float, bool}:
        raise ValueError("Audit data must contain only JSON values")


def _identifier(value: str, maximum: int | None = None) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or (maximum is not None and len(value.strip()) > maximum)
    ):
        raise ValueError("Invalid audit identifier")
    return value.strip()


async def ghi_nhat_ky(
    session: AsyncSession,
    *,
    actor_id: UUID | None,
    action: str,
    object_type: str,
    object_id: str,
    data: dict[str, object] | None = None,
    permission: str | None = None,
    actor_roles: Iterable[str] | None = None,
) -> UUID:
    """Flush one audit row and return its UUID; caller owns commit/rollback.

    actor_id=None denotes a system job. This helper does not authorize business
    actions and must be called inside the service's business transaction.
    """
    if data is not None and not isinstance(data, dict):
        raise ValueError("Audit data must be a JSON object")
    data = {} if data is None else data
    _validate_json(data)
    # Reject NaN/Infinity, and detach nested values from the caller's dictionary.
    snapshot = json.loads(json.dumps(data, allow_nan=False))
    if isinstance(actor_roles, str):
        raise TypeError("Audit roles must be a collection")
    roles = (
        sorted({_identifier(role, 100) for role in actor_roles})
        if actor_roles is not None
        else None
    )
    row = AuditLog(
        actor_id=actor_id,
        action=_identifier(action, 100),
        object_type=_identifier(object_type, 100),
        object_id=_identifier(object_id),
        data=snapshot,
        permission=_identifier(permission, 100) if permission is not None else None,
        actor_roles=roles,
    )
    session.add(row)
    await session.flush()
    return row.id
