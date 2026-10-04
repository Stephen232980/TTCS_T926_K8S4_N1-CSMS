"""S-26: lưu báo cáo JSON giữa simulator và bộ xác minh Compose/CI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_report(path: str, report: dict[str, Any]) -> None:
    """Write one complete simulator result without exposing authorization tags."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_report(path: str) -> dict[str, Any]:
    """Read a report and reject malformed JSON before it can hide a CI failure."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Simulator report must contain a JSON object")
    return value
