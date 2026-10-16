"""Staging host helper; never restarts or changes the application container."""

import argparse
import ast
import json
import os
import pathlib
import subprocess
import time

ROOT = pathlib.Path("/home/azureadmin/csms-staging-demo")
NAME = "csms-staging-demo-simulator"
LABEL = "csms.demo.namespace=csms-staging-demo"


def docker(*args, check=True):
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True
    )


def inspect(name):
    r = docker("inspect", name, check=False)
    return json.loads(r.stdout)[0] if r.returncode == 0 else None


def guarded():
    c = inspect(NAME)
    if c and c["Config"]["Labels"].get("csms.demo.namespace") != "csms-staging-demo":
        raise RuntimeError("Container name belongs to another process")
    return c


def stop():
    c = guarded()
    if not c or not c["State"]["Running"]:
        print("Demo already stopped; history retained.")
        return
    (ROOT / "stop.request").touch()
    docker("stop", "--time", "90", NAME)
    c = inspect(NAME)
    print("Demo stopped; history retained; exit=" + str(c["State"]["ExitCode"]))
    if c["State"]["ExitCode"] != 0:
        raise RuntimeError(
            "Simulator did not exit cleanly; inspect active demo sessions before restarting"
        )


def start(*, seed=True, mounted=False):
    c = guarded()
    if c and c["State"]["Running"]:
        app = inspect("csms-app")
        if app and c["Config"]["Image"] != app["Config"]["Image"]:
            raise RuntimeError("Backend image changed; stop then start the simulator")
        print("Demo already running.")
        status()
        runtime = ROOT / "runtime.json"
        if not runtime.exists() or json.loads(runtime.read_text()).get("online") != 20:
            raise RuntimeError(
                "Simulator running but not all 20 chargers online; inspect logs"
            )
        return
    app = inspect("csms-app")
    if not app or not app["State"]["Running"]:
        raise RuntimeError("Staging backend not running")
    configuration = dict(v.split("=", 1) for v in app["Config"]["Env"] if "=" in v)
    for flag in ["BILLING_AVAILABLE_CONFIRMS_UNPLUG", "DEMO_DRIVER_UNPLUG_ENABLED"]:
        if configuration.get(flag, "false").lower() not in {"true", "1", "yes"}:
            raise RuntimeError(
                "Enable "
                + flag
                + " on the staging backend before starting this demo version"
            )
    if not seed:
        manifest = json.loads((ROOT / "state.json").read_text())
        if (
            manifest.get("namespace") != "csms-staging-demo"
            or len(manifest.get("chargers", [])) != 20
        ):
            raise RuntimeError("Missing existing demo manifest; no reseed performed")
        if (
            not (ROOT / "accounts.json").is_file()
            or not (ROOT / "staging_demo.py").is_file()
        ):
            raise RuntimeError("Missing existing demo accounts or mounted script")
    network = next(iter(app["NetworkSettings"]["Networks"]))
    image = app["Config"]["Image"]
    envfile = ROOT / "runtime.private.env"
    envfile.write_text("\n".join(app["Config"]["Env"]) + "\n")
    envfile.chmod(0o600)
    base = [
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--network",
        network,
        "--env-file",
        str(envfile),
        "--label",
        LABEL,
        "--cpus",
        "0.5",
        "--memory",
        "384m",
        "-v",
        str(ROOT) + ":/demo",
        "-w",
        "/app",
        "-e",
        "CSMS_DEMO_DIR=/demo",
    ]
    try:
        # No credentials appear in command lines or captured output.
        if seed:
            r = docker(
                "run",
                "--rm",
                *base,
                image,
                "python",
                "/app/scripts/staging_demo.py",
                "seed",
                check=False,
            )
            print(r.stdout.strip())
            if r.returncode:
                raise RuntimeError(
                    "Fixture preparation failed; existing data retained. "
                    + r.stdout.strip()
                )
        if c:
            docker("rm", NAME)
        (ROOT / "stop.request").unlink(missing_ok=True)
        (ROOT / "runtime.json").unlink(missing_ok=True)
        docker(
            "run",
            "-d",
            "--name",
            NAME,
            "--restart",
            "unless-stopped",
            *base,
            image,
            "python",
            "-u",
            "/demo/staging_demo.py" if mounted else "/app/scripts/staging_demo.py",
            "live",
        )
    finally:
        envfile.unlink(missing_ok=True)
    for _ in range(75):
        c = guarded()
        if not c["State"]["Running"]:
            raise RuntimeError("Simulator stopped during startup; inspect logs")
        runtime = ROOT / "runtime.json"
        if runtime.exists():
            try:
                if json.loads(runtime.read_text())["online"] == 20:
                    status()
                    return
            except (ValueError, KeyError):
                pass
        time.sleep(1)
    status()
    raise RuntimeError("Not all 20 chargers ready within 75 seconds")


def assert_idle():
    """No data writes: refuse to replace a running demo with active work."""
    code = """import asyncio,json
from sqlalchemy import text
from src.entrypoints.http import app
from src.platform.database.session import SessionFactory
async def main():
 async with SessionFactory() as db:
  queries = [
   "SELECT count(*) FROM charging_sessions s JOIN charge_points p ON p.id=s.charge_point_id WHERE p.code LIKE 'DEMO-STG-%' AND (s.ended_at IS NULL OR (s.billing_lifecycle_version=1 AND s.connector_released_at IS NULL))",
   "SELECT count(*) FROM reservations r JOIN charge_points p ON p.id=r.charge_point_id WHERE p.code LIKE 'DEMO-STG-%' AND r.status IN ('pending','active','uncertain','cancel_pending','expiry_release_pending')",
   "SELECT count(*) FROM driver_start_requests r JOIN connectors c ON c.id=r.connector_id JOIN charge_points p ON p.id=c.charge_point_id WHERE p.code LIKE 'DEMO-STG-%' AND r.status IN ('Pending','Accepted')",
   "SELECT count(*) FROM station_power s WHERE s.enabled AND EXISTS (SELECT 1 FROM charge_points p WHERE p.station_id=s.station_id AND p.code LIKE 'DEMO-STG-%')"
  ]
  print(json.dumps([await db.scalar(text(q)) for q in queries]))
asyncio.run(main())"""
    r = subprocess.run(
        ["docker", "exec", "-i", "csms-app", "python", "-"],
        input=code,
        text=True,
        capture_output=True,
        check=True,
    )
    if json.loads(r.stdout) != [0, 0, 0, 0]:
        raise RuntimeError(
            "Active demo sessions/holds/start intents or enabled power control; update refused"
        )


def update():
    """Explicit post-merge refresh; never seed or change backend configuration."""
    c = guarded()
    app = inspect("csms-app")
    if not c or not c["State"]["Running"] or not app or not app["State"]["Running"]:
        raise RuntimeError("Backend and existing demo must both be running")
    configuration = dict(v.split("=", 1) for v in app["Config"]["Env"] if "=" in v)
    if any(
        configuration.get(flag, "false").lower() not in {"true", "1", "yes"}
        for flag in ("BILLING_AVAILABLE_CONFIRMS_UNPLUG", "DEMO_DRIVER_UNPLUG_ENABLED")
    ):
        raise RuntimeError(
            "Required demo flags are disabled; existing simulator left running"
        )
    manifest = json.loads((ROOT / "state.json").read_text())
    if (
        manifest.get("namespace") != "csms-staging-demo"
        or len(manifest.get("chargers", [])) != 20
    ):
        raise RuntimeError("Invalid demo manifest; update refused")
    if not (ROOT / "accounts.json").is_file():
        raise RuntimeError("Missing existing demo accounts; update refused")
    assert_idle()
    candidate = ROOT / "staging_demo.candidate.py"
    docker("cp", "csms-app:/app/scripts/staging_demo.py", str(candidate))
    source = candidate.read_text(encoding="utf-8")
    ast.parse(source)
    if "demo-3-smart-charging" not in source:
        raise RuntimeError(
            "Backend image does not contain the reviewed SmartCharging demo"
        )
    # Running /demo/staging_demo.py puts /demo ahead of the editable image
    # package. A legacy /demo/scripts therefore shadows /app/scripts entirely.
    dependencies = []
    scripts = ROOT / "scripts"
    if scripts.exists() and not scripts.is_dir():
        raise RuntimeError("Mounted demo scripts path must be a directory")
    if scripts.is_symlink() or any(
        (scripts / name).is_symlink()
        for name in ("__init__.py", "ocpp_control_simulator.py")
    ):
        raise RuntimeError("Unexpected symlink in mounted demo dependencies")
    for name in ("__init__.py", "ocpp_control_simulator.py"):
        prepared = ROOT / (name + ".candidate")
        docker("cp", "csms-app:/app/scripts/" + name, str(prepared))
        tree = ast.parse(prepared.read_text(encoding="utf-8"))
        if name == "ocpp_control_simulator.py":
            fields = {
                field.target.id
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == "ConnectorState"
                for field in node.body
                if isinstance(field, ast.AnnAssign)
                and isinstance(field.target, ast.Name)
            }
            if not {"default_limit_w", "transaction_limit_w"} <= fields:
                raise RuntimeError("Image simulator lacks SmartCharging state")
        dependencies.append((prepared, scripts / name))
    current = ROOT / "staging_demo.py"
    if not current.is_file():
        raise RuntimeError("Existing mounted script required; update refused")
    backup = ROOT / ("staging_demo.backup-" + str(time.time_ns()) + ".py")
    backup.write_bytes(current.read_bytes())
    backup.chmod(0o600)
    stamp = str(time.time_ns())
    for _, current_dependency in dependencies:
        if current_dependency.exists():
            dependency_backup = ROOT / (current_dependency.name + ".backup-" + stamp)
            dependency_backup.write_bytes(current_dependency.read_bytes())
            dependency_backup.chmod(0o600)
    assert_idle()
    stop()
    # Keep the stopped container until startup is validated, so an unsuccessful
    # stop never leads to a script replacement. Existing profile/reservation files stay.
    candidate.replace(current)
    scripts.mkdir(exist_ok=True)
    for prepared, current_dependency in dependencies:
        prepared.replace(current_dependency)
    try:
        start(seed=False, mounted=True)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        # New sessions may have appeared after startup: never kill them to roll back.
        print(
            "Update not confirmed; backup: "
            + str(backup)
            + "; inspect demo before retry"
        )
        raise
    print(
        "Updated from "
        + app["Config"]["Image"]
        + "; seed skipped; backup: "
        + str(backup)
    )


def status():
    c = guarded()
    runtime = ROOT / "runtime.json"
    result = {"running": bool(c and c["State"]["Running"]), "online": 0, "total": 20}
    if result["running"] and runtime.exists():
        result.update(json.loads(runtime.read_text()))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["start", "update", "stop", "status", "logs"])
    a = p.parse_args()
    try:
        if a.action == "start":
            start()
        elif a.action == "update":
            update()
        elif a.action == "stop":
            stop()
        elif a.action == "status":
            status()
        else:
            print(docker("logs", "--tail", "45", NAME).stdout)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as e:
        print(str(e))
        raise SystemExit(1)
