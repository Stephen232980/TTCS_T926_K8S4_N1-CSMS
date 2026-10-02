"""S-07 OCPP 1.6J frame models and JSON codec shared by all handlers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import cast

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
type JsonObject = dict[str, JsonValue]


class OcppMessageType(IntEnum):
    """S-07 numeric message types defined by OCPP 1.6J."""

    CALL = 2
    CALL_RESULT = 3
    CALL_ERROR = 4


class OcppErrorCode(StrEnum):
    """S-07 standard OCPP error codes emitted by the frame layer."""

    FORMATION_VIOLATION = "FormationViolation"
    INTERNAL_ERROR = "InternalError"
    NOT_IMPLEMENTED = "NotImplemented"
    PROTOCOL_ERROR = "ProtocolError"


@dataclass(frozen=True, slots=True)
class Call:
    """S-07 OCPP request: [2, message_id, action, payload]."""

    message_id: str
    action: str
    payload: JsonObject

    def as_list(self) -> list[object]:
        return [OcppMessageType.CALL, self.message_id, self.action, self.payload]


@dataclass(frozen=True, slots=True)
class CallResult:
    """S-07 OCPP success response: [3, message_id, payload]."""

    message_id: str
    payload: JsonObject

    def as_list(self) -> list[object]:
        return [OcppMessageType.CALL_RESULT, self.message_id, self.payload]


@dataclass(frozen=True, slots=True)
class CallError:
    """S-07 OCPP error response: [4, message_id, code, description, details]."""

    message_id: str
    code: str
    description: str
    details: JsonObject

    def as_list(self) -> list[object]:
        return [
            OcppMessageType.CALL_ERROR,
            self.message_id,
            self.code,
            self.description,
            self.details,
        ]


type OcppFrame = Call | CallResult | CallError


class OcppFrameViolation(ValueError):
    """S-07 malformed frame with a safe OCPP CALLERROR response context."""

    def __init__(
        self,
        message_id: str,
        description: str,
        code: OcppErrorCode = OcppErrorCode.FORMATION_VIOLATION,
    ) -> None:
        super().__init__(description)
        self.message_id = message_id
        self.description = description
        self.code = code

    def as_call_error(self) -> CallError:
        return CallError(
            message_id=self.message_id,
            code=self.code,
            description=self.description,
            details={},
        )


def decode_frame(raw_text: str) -> OcppFrame:
    """S-07 parse one WebSocket text frame into a validated OCPP frame model."""
    try:
        decoded = cast(object, json.loads(raw_text))
    except json.JSONDecodeError as error:
        raise OcppFrameViolation("", "Frame must be valid JSON.") from error

    if not isinstance(decoded, list):
        raise OcppFrameViolation("", "Frame must be a JSON array.")

    message_id = _message_id_from(decoded)
    if not decoded or type(decoded[0]) is not int:
        raise OcppFrameViolation(message_id, "Frame type must be an integer.")

    frame_type = decoded[0]
    if frame_type == OcppMessageType.CALL:
        return _decode_call(decoded, message_id)
    if frame_type == OcppMessageType.CALL_RESULT:
        return _decode_call_result(decoded, message_id)
    if frame_type == OcppMessageType.CALL_ERROR:
        return _decode_call_error(decoded, message_id)
    raise OcppFrameViolation(message_id, "Frame type is not supported.")


def encode_frame(frame: OcppFrame) -> str:
    """S-07 serialize a validated OCPP frame once before writing it to a socket."""
    return json.dumps(frame.as_list(), ensure_ascii=False, separators=(",", ":"))


def _message_id_from(frame: list[object]) -> str:
    if len(frame) > 1 and isinstance(frame[1], str):
        return frame[1]
    return ""


def _validate_message_id(message_id: str) -> None:
    if not message_id:
        raise OcppFrameViolation("", "Message ID must be a non-empty string.")


def _decode_call(frame: list[object], message_id: str) -> Call:
    if len(frame) != 4:
        raise OcppFrameViolation(message_id, "CALL must contain four elements.")
    _validate_message_id(message_id)

    action = frame[2]
    payload = frame[3]
    if not isinstance(action, str) or not action:
        raise OcppFrameViolation(message_id, "CALL action must be a non-empty string.")
    if not isinstance(payload, dict):
        raise OcppFrameViolation(message_id, "CALL payload must be an object.")
    return Call(message_id=message_id, action=action, payload=cast(JsonObject, payload))


def _decode_call_result(frame: list[object], message_id: str) -> CallResult:
    if len(frame) != 3:
        raise OcppFrameViolation(
            message_id,
            "CALLRESULT must contain three elements.",
        )
    _validate_message_id(message_id)

    payload = frame[2]
    if not isinstance(payload, dict):
        raise OcppFrameViolation(message_id, "CALLRESULT payload must be an object.")
    return CallResult(message_id=message_id, payload=cast(JsonObject, payload))


def _decode_call_error(frame: list[object], message_id: str) -> CallError:
    if len(frame) != 5:
        raise OcppFrameViolation(message_id, "CALLERROR must contain five elements.")
    _validate_message_id(message_id)

    raw_code, description, details = frame[2:]
    if not isinstance(raw_code, str) or not raw_code:
        raise OcppFrameViolation(
            message_id, "CALLERROR code must be a non-empty string."
        )
    if not isinstance(description, str):
        raise OcppFrameViolation(message_id, "CALLERROR description must be a string.")
    if not isinstance(details, dict):
        raise OcppFrameViolation(message_id, "CALLERROR details must be an object.")
    return CallError(
        message_id=message_id,
        code=raw_code,
        description=description,
        details=cast(JsonObject, details),
    )
