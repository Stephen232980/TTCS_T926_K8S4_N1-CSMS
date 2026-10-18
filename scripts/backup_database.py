"""Encrypted PostgreSQL backup and restore helpers for S-62."""

from __future__ import annotations

import argparse
import os
import secrets
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from cryptography.fernet import Fernet

MAGIC = b"CSMSBK01"
CHUNK_SIZE = 1024 * 1024
BACKUP_DIR = Path(os.getenv("S62_BACKUP_DIR", "backups"))


def _temporary_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")


def encrypt_backup(source: Path, destination: Path, key: bytes) -> None:
    """Encrypt a file in authenticated chunks and publish atomically."""
    if not source.is_file():
        raise FileNotFoundError(source)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(destination)

    try:
        cipher = Fernet(key)
        with source.open("rb") as inp, temporary.open("xb") as out:
            out.write(MAGIC)
            while chunk := inp.read(CHUNK_SIZE):
                token = cipher.encrypt(chunk)
                out.write(struct.pack(">I", len(token)))
                out.write(token)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def decrypt_backup(source: Path, destination: Path, key: bytes) -> None:
    """Authenticate and decrypt a backup before publishing the output."""
    if not source.is_file():
        raise FileNotFoundError(source)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(destination)

    try:
        cipher = Fernet(key)
        with source.open("rb") as inp, temporary.open("xb") as out:
            if inp.read(len(MAGIC)) != MAGIC:
                raise ValueError("Invalid or unsupported backup format")

            while True:
                length_bytes = inp.read(4)
                if not length_bytes:
                    break
                if len(length_bytes) != 4:
                    raise ValueError("Truncated backup: invalid chunk length")

                length = struct.unpack(">I", length_bytes)[0]
                if not 0 < length <= CHUNK_SIZE * 2:
                    raise ValueError("Invalid encrypted chunk length")

                token = inp.read(length)
                if len(token) != length:
                    raise ValueError("Truncated encrypted backup chunk")
                out.write(cipher.decrypt(token))

        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def prune_backups(directory: Path, keep: int = 14) -> None:
    """Keep only the newest encrypted backup files."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if not directory.exists():
        return

    backups = sorted(
        directory.glob("*.dump.enc"),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    for backup in backups[keep:]:
        backup.unlink()


def _database_config() -> tuple[str, str, str, int, str]:
    """Read DB connection settings without printing credentials."""
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")

    parsed = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.hostname:
        raise RuntimeError("DATABASE_URL must be a PostgreSQL URL")

    username = unquote(parsed.username or "")

    database = unquote(parsed.path.lstrip("/"))
    if not username or not database:
        raise RuntimeError("DATABASE_URL needs a username and database name")

    return (
        parsed.hostname,
        str(parsed.port or 5432),
        username,
        int(parsed.port or 5432),
        database,
    )


def _pg_env() -> dict[str, str]:
    """Build a subprocess environment without exposing secrets in arguments."""
    url = os.getenv("DATABASE_URL", "")
    parsed = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    env = os.environ.copy()
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    if parsed.path.strip("/"):
        env["PGDATABASE"] = unquote(parsed.path.strip("/"))
    env.setdefault("PGCONNECT_TIMEOUT", "10")
    return env


def _key() -> bytes:
    value = os.getenv("S62_BACKUP_KEY")
    if not value:
        raise RuntimeError(
            "S62_BACKUP_KEY is missing. Generate a Fernet key and "
            "store it securely outside the backup directory."
        )
    try:
        Fernet(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("S62_BACKUP_KEY is not a valid Fernet key") from exc
    return value.encode("ascii")


def create_backup() -> Path:
    """Dump PostgreSQL, encrypt it, then apply local retention."""
    key = _key()
    env = _pg_env()
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    plain = _temporary_path(BACKUP_DIR / f".{timestamp}.dump")
    encrypted = BACKUP_DIR / f"{timestamp}.dump.enc"

    try:
        with plain.open("xb") as output:
            subprocess.run(
                ["pg_dump", "--format=custom", "--no-password"],
                env=env,
                stdout=output,
                stderr=subprocess.PIPE,
                check=True,
            )
        encrypt_backup(plain, encrypted, key)
        prune_backups(BACKUP_DIR, keep=14)
        print(f"Encrypted backup created: {encrypted}")
        return encrypted
    finally:
        plain.unlink(missing_ok=True)


def restore_backup(source: Path) -> None:
    """Decrypt and restore a custom-format dump into the configured database."""
    key = _key()
    if not source.is_file():
        raise FileNotFoundError(source)

    plain = _temporary_path(source.with_suffix(".dump"))
    try:
        decrypt_backup(source, plain, key)
        subprocess.run(
            ["pg_restore", "--no-password", "--exit-on-error", str(plain)],
            env=_pg_env(),
            check=True,
        )
        print("Restore command completed successfully.")
    finally:
        plain.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="S-62 PostgreSQL backup utility")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="Create an encrypted database backup")
    restore = commands.add_parser("restore", help="Restore an encrypted backup")
    restore.add_argument("file", type=Path, help="Path to a .dump.enc file")
    args = parser.parse_args()

    try:
        if args.command == "backup":
            create_backup()
        else:
            restore_backup(args.file)
    except FileNotFoundError as exc:
        print(
            f"Required file or PostgreSQL client not found: {exc}",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError as exc:
        print(
            f"PostgreSQL command failed with exit code {exc.returncode}.",
            file=sys.stderr,
        )
        if exc.stderr:
            print(exc.stderr.decode(errors="replace"), file=sys.stderr)
        return 1
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"S-62 error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
