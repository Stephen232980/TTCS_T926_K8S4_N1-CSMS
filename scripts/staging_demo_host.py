"""Staging host helper; never restarts or changes the application container."""

import argparse
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


def start():
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
            "/app/scripts/staging_demo.py",
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


def status():
    c = guarded()
    runtime = ROOT / "runtime.json"
    result = {"running": bool(c and c["State"]["Running"]), "online": 0, "total": 20}
    if result["running"] and runtime.exists():
        result.update(json.loads(runtime.read_text()))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["start", "stop", "status", "logs"])
    a = p.parse_args()
    try:
        if a.action == "start":
            start()
        elif a.action == "stop":
            stop()
        elif a.action == "status":
            status()
        else:
            print(docker("logs", "--tail", "45", NAME).stdout)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as e:
        print(str(e))
        raise SystemExit(1)
