import shlex
from pathlib import Path

import yaml


def test_latency_gate_is_isolated_and_required_before_functional_suite() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
    )
    jobs = workflow["jobs"]
    quality = jobs["quality"]
    assert not quality.get("continue-on-error", False)
    pytest_steps = [
        (step, shlex.split(step["run"]))
        for step in quality["steps"]
        if step.get("run", "").lstrip().startswith("pytest")
    ]
    target = (
        "tests/test_charging_sessions.py::"
        "test_committed_replay_and_twenty_concurrent_meter_replies_under_200ms"
    )
    assert len(pytest_steps) == 2
    latency_step, latency_command = pytest_steps[0]
    functional_step, functional_command = pytest_steps[1]
    assert target in latency_command
    assert f"--deselect={target}" in functional_command
    for step in (latency_step, functional_step):
        assert not step.get("continue-on-error", False)
        assert "if" not in step
    assert jobs["simulator-scenario"]["needs"] == ["quality"]
    assert set(jobs["build"]["needs"]) == {"quality", "simulator-scenario"}
    assert jobs["build"]["if"] == "always()"
