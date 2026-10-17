"""Shared typed GetConfiguration/ChangeConfiguration transport for S-43/S-60."""

from uuid import UUID

from fastapi import WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, ValidationError

from src.modules.ocpp.connection_registry import OcppConnection


class ConfigurationKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: StrictStr
    readonly: StrictBool
    value: StrictStr | None = None


class ConfigurationReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configurationKey: list[ConfigurationKey] = []
    unknownKey: list[StrictStr] = []


async def configuration_call(
    connection: OcppConnection,
    action: str,
    payload: dict[str, object],
    request_id: UUID,
    timeout: float = 30,
) -> tuple[str, dict[str, object]]:
    try:
        reply = await connection.call(
            action, payload, timeout=timeout, message_id=str(request_id)
        )
        if reply.kind != 3:
            return (
                "NotSupported"
                if reply.error_code == "NotSupported"
                else "ProtocolError"
            ), {}
        if action == "GetConfiguration":
            parsed = ConfigurationReply.model_validate(reply.payload)
            names = [entry.key for entry in parsed.configurationKey]
            if len(names) != len(set(names)) or set(names) & set(parsed.unknownKey):
                return "ProtocolError", {}
            return "Accepted", parsed.model_dump()
        status = reply.payload.get("status")
        if not isinstance(status, str) or status not in {
            "Accepted",
            "Rejected",
            "NotSupported",
            "RebootRequired",
        }:
            return "ProtocolError", {}
        return str(status), {}
    except ValidationError:
        return "ProtocolError", {}
    except TimeoutError:
        return "Timeout", {}
    except (ConnectionError, OSError, RuntimeError, WebSocketDisconnect):
        return "Disconnected", {}
