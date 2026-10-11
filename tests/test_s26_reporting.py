"""A previous successful fleet run must never satisfy a new run's verifier."""

import pytest

from simulator import reporting, verify
from simulator.config import load_settings


def test_previous_report_is_rejected_after_restart(tmp_path, monkeypatch):
    local_marker = tmp_path / "local-run.json"
    monkeypatch.setattr(reporting, "LOCAL_RUN_MARKER", local_marker)
    path = str(tmp_path / "report.json")
    first = reporting.begin_run(path)
    reporting.write_report(path, {"run_id": first})
    assert reporting.report_ready(path)

    second = reporting.begin_run(path)
    assert second != first
    assert not reporting.report_ready(path)
    with pytest.raises(ValueError, match="current run"):
        reporting.read_current_report(path)

    reporting.write_report(path, {"run_id": second})
    assert reporting.report_ready(path)
    local_marker.unlink()
    assert not reporting.report_ready(path)


def test_healthcheck_rejects_another_process_report(tmp_path, monkeypatch):
    monkeypatch.setattr(reporting, "LOCAL_RUN_MARKER", tmp_path / "local.json")
    path = str(tmp_path / "report.json")
    reporting.begin_run(path)
    reporting.write_report(path + ".run.json", {"run_id": "another-process"})
    reporting.write_report(path, {"run_id": "another-process"})
    assert not reporting.report_ready(path)


@pytest.mark.asyncio
async def test_verifier_waits_for_the_current_run(tmp_path, monkeypatch):
    monkeypatch.setattr(reporting, "LOCAL_RUN_MARKER", tmp_path / "local.json")
    path = str(tmp_path / "report.json")
    first = reporting.begin_run(path)
    reporting.write_report(path, {"run_id": first})
    second = reporting.begin_run(path)
    waits = []

    async def complete_run(seconds):
        waits.append(seconds)
        reporting.write_report(path, {"run_id": second})

    monkeypatch.setattr(verify.asyncio, "sleep", complete_run)
    report = await verify._wait_for_report(
        load_settings({"SIMULATOR_REPORT_PATH": path})
    )
    assert waits == [1]
    assert report["run_id"] == second
