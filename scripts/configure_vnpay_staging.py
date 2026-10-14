"""Interactive, local-only configuration; does not restart/deploy any service."""

import argparse
import getpass
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

DOMAIN = "csms-staging.daominhtam2k6.id.vn"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    target = args.env_file.resolve(strict=True)
    original = target.read_text(encoding="utf-8")
    if not re.search(r"^DATABASE_URL=.+$", original, re.MULTILINE):
        raise SystemExit("Choose the existing backend env file containing DATABASE_URL")
    tmn = input("VNPAY TmnCode: ").strip()
    secret = getpass.getpass("VNPAY HashSecret (hidden): ")
    if not re.fullmatch(r"[A-Za-z0-9]{8}", tmn) or not re.fullmatch(
        r"[A-Za-z0-9]+", secret
    ):
        raise SystemExit("Invalid merchant code or secret; configuration unchanged")
    # Trust only the actual TLS proxy peer, not arbitrary X-Forwarded-For input.
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "csms-https",
            "--format",
            "{{json .NetworkSettings.Networks}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    networks = json.loads(result.stdout)
    address = networks["ttcs_t926_k8s4_n1-csms-main_default"]["IPAddress"]
    ipaddress.ip_address(address)
    updates = {
        "PAYMENT_GATEWAY": "sandbox",
        "PAYMENT_WEBHOOK_SECRET": secret,
        "VNPAY_TMN_CODE": tmn,
        "VNPAY_RETURN_URL": f"https://{DOMAIN}/api/v1/payments/vnpay/return",
        "PAYMENT_RETURN_URL": f"https://{DOMAIN}/wallet/topup/return",
        "AUTH_COOKIE_SECURE": "true",
        "FORWARDED_ALLOW_IPS": address,
    }
    lines = []
    for line in original.splitlines():
        key = line.partition("=")[0].strip()
        if key not in updates:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in updates.items())
    backup = target.with_name(
        target.name + ".before-vnpay-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    )
    backup_descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(backup_descriptor)
    shutil.copyfile(target, backup)
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".vnpay-env-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
        os.replace(temporary, target)
        target.chmod(0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print("Updated backend configuration; private backup saved. No service restarted.")
    print("Apply it through the normal staging deployment process.")


if __name__ == "__main__":
    main()
