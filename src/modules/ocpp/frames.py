"""OCPP 1.6J envelopes shared by incoming and outgoing calls."""

import json
from dataclasses import dataclass
from typing import Any, Literal


class FrameError(Exception):
    def __init__(self, message_id: str, code: str, description: str) -> None:
        self.message_id = message_id
        self.code = code
        self.description = description


@dataclass(frozen=True)
class Frame:
    kind: Literal[2, 3, 4]
    message_id: str
    payload: dict[str, Any]
    action: str = ""
    error_code: str = ""
    description: str = ""


def encode_frame(frame: Frame) -> str:
    if frame.kind == 2:
        value = [2, frame.message_id, frame.action, frame.payload]
    elif frame.kind == 3:
        value = [3, frame.message_id, frame.payload]
    else:
        value = [
            4,
            frame.message_id,
            frame.error_code,
            frame.description,
            frame.payload,
        ]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def error_frame(message_id: str, code: str, description: str) -> str:
    return encode_frame(
        Frame(4, message_id, {}, error_code=code, description=description)
    )


def _reject_constant(value: str) -> None:
    raise ValueError(value)


def decode_frame(raw: str) -> Frame:
    try:
        value = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise FrameError("", "FormationViolation", "Invalid JSON frame") from error
    uid = (
        value[1]
        if isinstance(value, list) and len(value) > 1 and isinstance(value[1], str)
        else ""
    )
    if (
        not isinstance(value, list)
        or not value
        or type(value[0]) is not int
        or value[0] not in (2, 3, 4)
    ):
        raise FrameError(uid, "FormationViolation", "Invalid message type")
    if not uid or len(uid) > 36:
        raise FrameError(uid[:36], "FormationViolation", "Invalid message identifier")
    kind = value[0]
    expected = {2: 4, 3: 3, 4: 5}[kind]
    if len(value) != expected:
        raise FrameError(uid, "FormationViolation", "Invalid frame length")
    if kind == 2:
        if not isinstance(value[2], str) or not value[2]:
            raise FrameError(uid, "TypeConstraintViolation", "Action must be a string")
        payload = value[3]
    elif kind == 3:
        payload = value[2]
    else:
        if not isinstance(value[2], str) or not isinstance(value[3], str):
            raise FrameError(uid, "TypeConstraintViolation", "Invalid error fields")
        payload = value[4]
    if not isinstance(payload, dict):
        raise FrameError(uid, "TypeConstraintViolation", "Payload must be an object")
    if kind == 2:
        return Frame(2, uid, payload, action=value[2])
    if kind == 3:
        return Frame(3, uid, payload)
    return Frame(4, uid, payload, error_code=value[2], description=value[3])
