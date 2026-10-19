"""S-62: authenticated streaming PostgreSQL backups and isolated restores."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from urllib.parse import parse_qs, unquote, urlsplit

from cryptography.fernet import Fernet, InvalidToken

MAGIC = b"CSMSBK02"
CHUNK_SIZE = 1024 * 1024
BACKUP_DIR = Path(os.getenv("S62_BACKUP_DIR", "backups"))


def _temporary_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")


def _private_open(path: Path) -> BinaryIO:
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


def encrypt_backup(source: Path, destination: Path, key: bytes) -> None:
    """Bind every chunk to its file/index, followed by an authenticated EOF."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(destination)
    cipher = Fernet(key)
    file_id = secrets.token_bytes(16)
    digest = hashlib.sha256()
    count = size = 0
    try:
        with source.open("rb") as inp, _private_open(temporary) as out:
            out.write(MAGIC + file_id)
            while chunk := inp.read(CHUNK_SIZE):
                digest.update(chunk)
                token = cipher.encrypt(
                    b"D" + file_id + struct.pack(">Q", count) + chunk
                )
                out.write(struct.pack(">I", len(token)) + token)
                count += 1
                size += len(chunk)
            token = cipher.encrypt(
                b"E" + file_id + struct.pack(">QQ", count, size) + digest.digest()
            )
            out.write(struct.pack(">I", len(token)) + token)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def decrypt_backup(source: Path, destination: Path, key: bytes) -> None:
    """Publish plaintext only after complete authentication; reject v1 archives."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(destination)
    cipher = Fernet(key)
    digest = hashlib.sha256()
    count = size = 0
    try:
        with source.open("rb") as inp, _private_open(temporary) as out:
            if inp.read(len(MAGIC)) != MAGIC:
                raise ValueError("Unsupported backup format; v1 must be recreated")
            file_id = inp.read(16)
            if len(file_id) != 16:
                raise ValueError("Truncated backup header")
            while True:
                length_bytes = inp.read(4)
                if len(length_bytes) != 4:
                    raise ValueError("Missing authenticated end of backup")
                length = struct.unpack(">I", length_bytes)[0]
                if not 0 < length <= CHUNK_SIZE * 2:
                    raise ValueError("Invalid encrypted chunk length")
                token = inp.read(length)
                if len(token) != length:
                    raise ValueError("Truncated encrypted chunk")
                payload = cipher.decrypt(token)
                if payload[:17] != b"D" + file_id:
                    expected = (
                        b"E"
                        + file_id
                        + struct.pack(">QQ", count, size)
                        + digest.digest()
                    )
                    if payload != expected or inp.read(1):
                        raise ValueError("Invalid backup manifest or trailing content")
                    break
                if len(payload) <= 25 or payload[17:25] != struct.pack(">Q", count):
                    raise ValueError("Invalid backup chunk order")
                chunk = payload[25:]
                digest.update(chunk)
                count += 1
                size += len(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def prune_backups(directory: Path, keep: int = 3) -> None:
    """Retention is a number of successful archives, explicitly not days."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    backups = sorted(
        directory.glob("*.dump.enc"),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    for backup in backups[keep:]:
        backup.unlink()


def _pg_env(variable: str = "DATABASE_URL") -> dict[str, str]:
    """Validate libpq settings; never fall back to an unrelated local database."""
    url = os.getenv(variable, "")
    parsed = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or not parsed.hostname
        or not parsed.username
        or not parsed.path.strip("/")
    ):
        raise RuntimeError(f"{variable} needs a PostgreSQL host, user and database")
    # Reject unsupported URL options rather than silently dropping TLS settings.
    options = parse_qs(parsed.query, strict_parsing=True)
    allowed = {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout"}
    if options.keys() - allowed:
        raise RuntimeError(f"Unsupported connection option in {variable}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(
        PGHOST=parsed.hostname,
        PGPORT=str(parsed.port or 5432),
        PGUSER=unquote(parsed.username),
        PGDATABASE=unquote(parsed.path.strip("/")),
        PGCONNECT_TIMEOUT="10",
    )
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    for name, values in options.items():
        if len(values) != 1:
            raise RuntimeError(f"Duplicate connection option in {variable}")
        env["PG" + name.upper()] = values[0]
    return env


def _key() -> bytes:
    key_file = os.getenv("S62_BACKUP_KEY_FILE")
    value = (
        Path(key_file).read_bytes().strip()
        if key_file
        else os.getenv("S62_BACKUP_KEY", "").encode("ascii")
    )
    if not value:
        raise RuntimeError("Configure S62_BACKUP_KEY_FILE outside the archive store")
    Fernet(value)
    return value


def _run(
    arguments: list[str],
    env: dict[str, str],
    *,
    stdout: BinaryIO | int | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        env=env,
        check=True,
        stderr=subprocess.PIPE,
        timeout=int(os.getenv("S62_COMMAND_TIMEOUT", "1800")),
        stdout=stdout,
    )


@contextmanager
def _backup_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".s62.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise RuntimeError(
            "Backup already running or stale .s62.lock; inspect job first"
        ) from None
    try:
        yield
    finally:
        lock.rmdir()


def _mirror(source: Path, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name
    temporary = _temporary_path(target)
    try:
        with source.open("rb") as inp, _private_open(temporary) as out:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        if _file_hash(source) != _file_hash(temporary):
            raise RuntimeError("Archive mirror checksum mismatch")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _file_hash(path: Path) -> bytes:
    with path.open("rb") as inp:
        return hashlib.file_digest(inp, "sha256").digest()


def create_backup() -> Path:
    """Mirror encrypted bytes before retention; failures preserve prior backups."""
    key, env = _key(), _pg_env()
    keep = int(os.getenv("S62_KEEP_COUNT", "3"))
    if keep < 1:
        raise ValueError("S62_KEEP_COUNT must be at least 1")
    mirror_value = os.getenv("S62_MIRROR_DIR")
    mirror = Path(mirror_value) if mirror_value else None
    if mirror is not None and mirror.resolve() == BACKUP_DIR.resolve():
        raise ValueError("Mirror must be a separate storage location")
    with (
        _backup_lock(BACKUP_DIR),
        tempfile.TemporaryDirectory(prefix="s62-") as scratch,
    ):
        plain = Path(scratch) / "database.dump"
        encrypted = BACKUP_DIR / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + f"-{secrets.token_hex(4)}.dump.enc"
        )
        with _private_open(plain) as out:
            _run(["pg_dump", "--format=custom", "--no-password"], env, stdout=out)
        encrypt_backup(plain, encrypted, key)
        if mirror is not None:
            _mirror(encrypted, mirror)
            prune_backups(mirror, keep)
        prune_backups(BACKUP_DIR, keep)
        print(f"Backup completed: {encrypted.name}; mirrored={mirror is not None}")
        return encrypted


def restore_backup(source: Path) -> None:
    """Require a distinct explicit restore URL and an empty disposable database."""
    key, target = _key(), _pg_env("S62_RESTORE_DATABASE_URL")
    if os.getenv("DATABASE_URL"):
        source_env = _pg_env()
        if all(target[k] == source_env[k] for k in ("PGHOST", "PGPORT", "PGDATABASE")):
            raise RuntimeError("Restore target must differ from the source database")
    count = _run(
        [
            "psql",
            "-X",
            "--no-password",
            "--set=ON_ERROR_STOP=1",
            "-Atc",
            (
                "SELECT count(*) FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' "
                "AND nspname NOT IN ('public', 'information_schema') "
                "UNION ALL SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                "ON n.oid=c.relnamespace WHERE n.nspname='public' "
                "UNION ALL SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname='public' "
                "UNION ALL SELECT count(*) FROM pg_type t JOIN pg_namespace n "
                "ON n.oid=t.typnamespace WHERE n.nspname='public';"
            ),
        ],
        target,
        stdout=subprocess.PIPE,
    )
    if count.stdout.strip() != b"0\n0\n0\n0":
        raise RuntimeError("Restore requires an empty target database")
    with tempfile.TemporaryDirectory(prefix="s62-restore-") as scratch:
        plain = Path(scratch) / "database.dump"
        decrypt_backup(source, plain, key)
        _run(
            [
                "pg_restore",
                "--no-password",
                "--exit-on-error",
                "--single-transaction",
                "--dbname",
                target["PGDATABASE"],
                str(plain),
            ],
            target,
        )
    print("Restore committed; run application/data acceptance checks before use.")


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup")
    restore = commands.add_parser("restore")
    restore.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            create_backup()
        else:
            restore_backup(args.file)
    except (
        RuntimeError,
        ValueError,
        OSError,
        InvalidToken,
        subprocess.SubprocessError,
    ):
        # libpq stderr can contain SQL/data/connection details. Keep it off job logs.
        print(
            "S-62 job failed; check configuration, archive/key and PostgreSQL access.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
