"""The optional fleet must not prevent ordinary Compose use with an old env."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_compose_without_simulator_password(tmp_path):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose is unavailable")
    environment = dict(os.environ)
    environment.pop("SIMULATOR_OPERATOR_PASSWORD", None)
    environment.update(
        POSTGRES_DB="review", POSTGRES_USER="review", POSTGRES_PASSWORD="review"
    )
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [docker, "compose", "--env-file", str(empty_env), "config", "--services"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.split()) == {"app", "db"}
