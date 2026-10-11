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
    internal_target = (
        "tests/test_charging_sessions.py::"
        "test_committed_replay_and_twenty_concurrent_meter_replies_under_200ms"
    )
    socket_target = (
        "tests/test_s19_meter_latency.py::"
        "test_twenty_real_sockets_periodic_meter_replies_under_200ms"
    )
    assert len(pytest_steps) == 3
    _, functional_command = pytest_steps[2]
    for (_, command), target in zip(
        pytest_steps[:2], (internal_target, socket_target), strict=True
    ):
        assert target in command
        assert "--deselect" not in " ".join(command)
        assert "||" not in command
        assert "-s" in command
        assert f"--deselect={target}" in functional_command
    for step, _ in pytest_steps:
        assert not step.get("continue-on-error", False)
        assert "if" not in step
    assert jobs["simulator-scenario"]["needs"] == ["quality"]
    assert set(jobs["build"]["needs"]) == {"quality", "simulator-scenario"}
    assert jobs["build"]["if"] == "always()"
