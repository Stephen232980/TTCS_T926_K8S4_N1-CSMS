"""Configuration preserves DB settings and never prints merchant credentials."""

import json
import subprocess
import sys

import pytest

from scripts import configure_vnpay_staging as script


def test_help_never_creates_configuration(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "scripts.configure_vnpay_staging", "--help"],
        capture_output=True,
        text=True,
        check=True,
        cwd=".",
    )
    assert "--env-file" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_private_update_preserves_database_and_backup(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    original = "DATABASE_URL=postgresql://private-db\nPAYMENT_GATEWAY=fake\nPAYMENT_WEBHOOK_SECRET=old\nOTHER=keep\n"
    path.write_text(original)
    monkeypatch.setattr(sys, "argv", ["configure", "--env-file", str(path)])
    monkeypatch.setattr("builtins.input", lambda _: "TEST1234")
    monkeypatch.setattr(script.getpass, "getpass", lambda _: "PrivateSecret123")
    monkeypatch.setattr(
        script.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {"ttcs_t926_k8s4_n1-csms-main_default": {"IPAddress": "172.20.0.8"}}
            ),
        ),
    )
    script.main()
    content = path.read_text()
    assert "DATABASE_URL=postgresql://private-db" in content and "OTHER=keep" in content
    assert (
        content.count("PAYMENT_GATEWAY=") == 1 and "PAYMENT_GATEWAY=sandbox" in content
    )
    assert (
        "AUTH_COOKIE_SECURE=true" in content
        and "FORWARDED_ALLOW_IPS=172.20.0.8" in content
    )
    assert "PAYMENT_WEBHOOK_SECRET=PrivateSecret123" in content
    backups = list(tmp_path.glob(".env.before-vnpay-*"))
    assert len(backups) == 1 and backups[0].read_text() == original
    assert "PrivateSecret123" not in capsys.readouterr().out
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
        assert backups[0].stat().st_mode & 0o777 == 0o600


def test_invalid_input_leaves_env_unchanged(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    original = "DATABASE_URL=postgresql://private-db\n"
    path.write_text(original)
    monkeypatch.setattr(sys, "argv", ["configure", "--env-file", str(path)])
    monkeypatch.setattr("builtins.input", lambda _: "invalid")
    monkeypatch.setattr(script.getpass, "getpass", lambda _: "Secret")
    with pytest.raises(SystemExit):
        script.main()
    assert path.read_text() == original
    assert len(list(tmp_path.iterdir())) == 1
