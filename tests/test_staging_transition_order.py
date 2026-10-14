"""Exercise the deployment script with fake infrastructure, never a real daemon."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="Linux deployment shell harness")
@pytest.mark.parametrize(
    "blocked,fail_migration", [(True, False), (False, True), (False, False)]
)
def test_no_runtime_before_successful_migration(tmp_path, blocked, fail_migration):
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/bin/sh
echo "$*" >> "$DOCKER_TRACE"
case "$*" in
  'ps -a --format '*|'ps --format '*) echo csms-app ;;
  'inspect -f '*) echo false ;;
  *'python scripts/verify_settlement_transition.py'*) [ "$BLOCK_PREFLIGHT" = 0 ] || exit 1 ;;
  *'alembic upgrade head'*) [ "$FAIL_MIGRATION" = 0 ] || exit 1 ;;
  *'python -c '*) echo csms_runtime ;;
esac
exit 0
"""
    )
    docker.chmod(0o755)
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/sh\nprintf 200\n")
    curl.chmod(0o755)
    env_file = tmp_path / "runtime.env"
    env_file.write_text("")
    Path(str(env_file) + ".migrations").write_text("")
    trace = tmp_path / "commands.log"
    result = subprocess.run(
        ["bash", "scripts/deploy_staging.sh", "test-image"],
        env=os.environ
        | {
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "DOCKER_TRACE": str(trace),
            "BLOCK_PREFLIGHT": str(int(blocked)),
            "FAIL_MIGRATION": str(int(fail_migration)),
            "ENV_FILE": str(env_file),
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    commands = trace.read_text().splitlines()
    runtimes = [
        i for i, command in enumerate(commands) if command.startswith("run -d ")
    ]
    if blocked or fail_migration:
        assert result.returncode != 0
        assert runtimes == []
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        migration = next(
            i for i, command in enumerate(commands) if "alembic upgrade head" in command
        )
        permissions = next(
            i
            for i, command in enumerate(commands)
            if "grant_runtime_permissions.py --role" in command
        )
        assert runtimes and all(i > permissions > migration for i in runtimes)
