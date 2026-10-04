"""S-26: lưu báo cáo JSON giữa simulator và bộ xác minh Compose/CI."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import gettempdir
from typing import Any
from uuid import uuid4

LOCAL_RUN_MARKER = Path(gettempdir()) / "s26-simulator-run.json"


def begin_run(path: str) -> str:
    """Bind reports to this client process, including across container restarts."""
    run_id = str(uuid4())
    marker = {"run_id": run_id}
    write_report(str(LOCAL_RUN_MARKER), marker)
    write_report(path + ".run.json", marker)
    return run_id


def read_current_report(path: str) -> dict[str, Any]:
    """Reject a previous run's report even when its sessions still exist."""
    marker = read_report(path + ".run.json")
    report = read_report(path)
    if not marker.get("run_id") or report.get("run_id") != marker["run_id"]:
        raise ValueError("Simulator report does not belong to the current run")
    return report


def report_ready(path: str) -> bool:
    """Healthcheck accepts only a complete report from this client process."""
    try:
        marker = read_report(str(LOCAL_RUN_MARKER))
        report = read_current_report(path)
        return bool(marker.get("run_id")) and report.get("run_id") == marker["run_id"]
    except (OSError, ValueError, TypeError):
        return False


def write_report(path: str, report: dict[str, Any]) -> None:
    """Write one complete simulator result without exposing authorization tags."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4()}.tmp")
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def read_report(path: str) -> dict[str, Any]:
    """Read a report and reject malformed JSON before it can hide a CI failure."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Simulator report must contain a JSON object")
    return value
