"""A merged image must reach the mounted demo without reseeding live data."""

import json
from unittest.mock import Mock

import pytest

from scripts import staging_demo_host as host


@pytest.fixture
def update_env(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "ROOT", tmp_path)
    app = {
        "State": {"Running": True},
        "Config": {
            "Image": "reviewed:sha",
            "Env": [
                "BILLING_AVAILABLE_CONFIRMS_UNPLUG=true",
                "DEMO_DRIVER_UNPLUG_ENABLED=true",
            ],
        },
    }
    monkeypatch.setattr(host, "guarded", lambda: {"State": {"Running": True}})
    monkeypatch.setattr(host, "inspect", lambda name: app)
    (tmp_path / "state.json").write_text(
        json.dumps({"namespace": "csms-staging-demo", "chargers": [{}] * 20})
    )
    (tmp_path / "accounts.json").write_text("private original accounts")
    (tmp_path / "staging_demo.py").write_text("# existing reservation-capable script")
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        assert args[:2] == ("cp", "csms-app:/app/scripts/staging_demo.py")
        (tmp_path / "staging_demo.candidate.py").write_text(
            "# demo-3-smart-charging\npass\n"
        )

    monkeypatch.setattr(host, "docker", docker)
    idle = Mock()
    stop = Mock()
    start = Mock()
    monkeypatch.setattr(host, "assert_idle", idle)
    monkeypatch.setattr(host, "stop", stop)
    monkeypatch.setattr(host, "start", start)
    return tmp_path, app, idle, stop, start, calls


def test_update_uses_reviewed_image_skips_seed_and_preserves_accounts(update_env):
    root, _, idle, stop, start, calls = update_env
    host.update()
    assert idle.call_count == 2
    stop.assert_called_once_with()
    start.assert_called_once_with(seed=False, mounted=True)
    assert (root / "accounts.json").read_text() == "private original accounts"
    assert "demo-3-smart-charging" in (root / "staging_demo.py").read_text()
    backups = list(root.glob("staging_demo.backup-*.py"))
    assert (
        len(backups) == 1
        and backups[0].read_text() == "# existing reservation-capable script"
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "gate", ["active_work", "disabled_flags", "bad_manifest", "missing_accounts"]
)
def test_preflight_failure_leaves_running_demo_untouched(update_env, gate):
    root, app, idle, stop, start, calls = update_env
    if gate == "active_work":
        idle.side_effect = RuntimeError("active demo work")
    elif gate == "disabled_flags":
        app["Config"]["Env"] = []
    elif gate == "bad_manifest":
        (root / "state.json").write_text("{}")
    elif gate == "missing_accounts":
        (root / "accounts.json").unlink()
    with pytest.raises(RuntimeError):
        host.update()
    stop.assert_not_called()
    start.assert_not_called()
    assert not calls
    assert (
        root / "staging_demo.py"
    ).read_text() == "# existing reservation-capable script"


def test_activity_during_preparation_prevents_stop(update_env):
    root, _, idle, stop, start, _ = update_env
    idle.side_effect = [None, RuntimeError("start intent appeared")]
    with pytest.raises(RuntimeError, match="start intent"):
        host.update()
    stop.assert_not_called()
    start.assert_not_called()
    assert (
        root / "staging_demo.py"
    ).read_text() == "# existing reservation-capable script"


def test_failed_start_preserves_backup_without_killing_new_work(update_env):
    root, _, _, stop, start, _ = update_env
    start.side_effect = RuntimeError("not all chargers online")
    with pytest.raises(RuntimeError):
        host.update()
    stop.assert_called_once()
    assert len(list(root.glob("staging_demo.backup-*.py"))) == 1


def test_start_existing_demo_uses_mount_without_any_seed(update_env, monkeypatch):
    from types import SimpleNamespace

    root, app, _, _, _, calls = update_env
    # Restore the real function replaced by the update fixture.
    import importlib.util

    spec = importlib.util.spec_from_file_location("host_start_only", host.__file__)
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    real.ROOT = root
    monkeypatch.setattr(real.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(real.os, "getgid", lambda: 1000, raising=False)
    app["NetworkSettings"] = {"Networks": {"demo-network": {}}}
    existing = {
        "State": {"Running": False},
        "Config": {"Labels": {"csms.demo.namespace": "csms-staging-demo"}},
    }
    monkeypatch.setattr(real, "guarded", lambda: existing)
    monkeypatch.setattr(
        real,
        "inspect",
        lambda name: app if name == "csms-app" else {"State": {"Running": True}},
    )

    def docker(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("run", "-d"):
            existing["State"]["Running"] = True
            (root / "runtime.json").write_text('{"online":20}')
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(real, "docker", docker)
    real.start(seed=False, mounted=True)
    assert not any("seed" in args for args in calls)
    run = next(args for args in calls if args[:2] == ("run", "-d"))
    assert "/demo/staging_demo.py" in run and "reviewed:sha" in run
    assert (root / "accounts.json").read_text() == "private original accounts"
    assert not (root / "runtime.private.env").exists()
