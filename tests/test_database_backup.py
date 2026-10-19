from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from scripts.backup_database import decrypt_backup, encrypt_backup


def test_encrypt_and_decrypt_backup(tmp_path: Path) -> None:
    source = tmp_path / "database.dump"
    encrypted = tmp_path / "database.dump.enc"
    restored = tmp_path / "restored.dump"
    original = b"sample PostgreSQL backup data"
    key = Fernet.generate_key()
    source.write_bytes(original)

    encrypt_backup(source, encrypted, key)
    decrypt_backup(encrypted, restored, key)

    assert encrypted.is_file()
    assert encrypted.read_bytes() != original
    assert restored.read_bytes() == original
    assert source.read_bytes() == original


def test_encrypt_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        encrypt_backup(
            tmp_path / "missing.dump",
            tmp_path / "backup.enc",
            Fernet.generate_key(),
        )


def test_wrong_key_cannot_decrypt(tmp_path: Path) -> None:
    source = tmp_path / "database.dump"
    encrypted = tmp_path / "database.dump.enc"
    restored = tmp_path / "restored.dump"
    source.write_bytes(b"sample data")

    encrypt_backup(source, encrypted, Fernet.generate_key())

    with pytest.raises(InvalidToken):
        decrypt_backup(encrypted, restored, Fernet.generate_key())

    assert not restored.exists()


from scripts.backup_database import prune_backups


def test_prune_backups_keeps_latest_three_by_default(tmp_path: Path) -> None:
    import os

    backups = []
    for index in range(16):
        path = tmp_path / f"backup-{index:02}.dump.enc"
        path.write_bytes(b"backup")
        timestamp = 1_800_000_000 + index
        os.utime(path, (timestamp, timestamp))
        backups.append(path)

    prune_backups(tmp_path)

    remaining = sorted(tmp_path.glob("*.dump.enc"))
    assert len(remaining) == 3
    assert [path.name for path in remaining] == [
        f"backup-{index:02}.dump.enc" for index in range(13, 16)
    ]


@pytest.mark.parametrize(
    "damage", ["cut_end", "cut_data", "partial", "swap", "duplicate", "edit", "append"]
)
def test_whole_archive_authentication(tmp_path, damage):
    import struct

    from scripts.backup_database import CHUNK_SIZE, MAGIC

    source = tmp_path / "source"
    archive = tmp_path / "archive"
    result = tmp_path / "result"
    source.write_bytes(b"A" * CHUNK_SIZE + b"B" * 43)
    key = Fernet.generate_key()
    encrypt_backup(source, archive, key)
    data = archive.read_bytes()
    header = data[: len(MAGIC) + 16]
    frames = []
    pos = len(header)
    while pos < len(data):
        size = struct.unpack(">I", data[pos : pos + 4])[0]
        frames.append(data[pos : pos + 4 + size])
        pos += 4 + size
    variants = {
        "cut_end": header + b"".join(frames[:-1]),
        "cut_data": header + frames[0] + frames[-1],
        "partial": data[:-7],
        "swap": header + frames[1] + frames[0] + frames[2],
        "duplicate": header + frames[0] + b"".join(frames),
        "edit": data[:40] + bytes([data[40] ^ 1]) + data[41:],
        "append": data + b"extra",
    }
    archive.write_bytes(variants[damage])
    result.write_bytes(b"previous valid output")
    with pytest.raises((ValueError, InvalidToken)):
        decrypt_backup(archive, result, key)
    assert result.read_bytes() == b"previous valid output"
    assert not list(tmp_path.glob("*.tmp"))


def test_empty_archive_and_wrong_key(tmp_path):
    source, archive, result = (
        tmp_path / name for name in ("source", "archive", "result")
    )
    source.write_bytes(b"")
    key = Fernet.generate_key()
    encrypt_backup(source, archive, key)
    with pytest.raises(InvalidToken):
        decrypt_backup(archive, result, Fernet.generate_key())
    decrypt_backup(archive, result, key)
    assert result.read_bytes() == b""


def test_chunks_from_another_archive_are_rejected(tmp_path):
    from scripts.backup_database import MAGIC

    source = tmp_path / "source"
    first, second = tmp_path / "first", tmp_path / "second"
    source.write_bytes(b"same content")
    key = Fernet.generate_key()
    encrypt_backup(source, first, key)
    encrypt_backup(source, second, key)
    first.write_bytes(
        first.read_bytes()[: len(MAGIC) + 16] + second.read_bytes()[len(MAGIC) + 16 :]
    )
    with pytest.raises(ValueError):
        decrypt_backup(first, tmp_path / "result", key)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "postgresql://localhost/db",
        "sqlite:///db",
        "postgresql://u@localhost/",
        "postgresql://u@localhost/db?bad=1",
    ],
)
def test_connection_configuration_fails_closed(monkeypatch, url):
    from scripts.backup_database import _pg_env

    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(RuntimeError):
        _pg_env()


def test_tls_and_encoded_credentials(monkeypatch):
    from scripts.backup_database import _pg_env

    monkeypatch.setenv("PGPASSWORD", "wrong")
    monkeypatch.setenv("PGSERVICE", "unrelated")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:p%40ss@host/db?sslmode=verify-full&sslrootcert=%2Fkeys%2Fca.pem",
    )
    env = _pg_env()
    assert env["PGPASSWORD"] == "p@ss"
    assert env["PGSSLMODE"] == "verify-full"
    assert env["PGSSLROOTCERT"] == "/keys/ca.pem"
    assert "PGSERVICE" not in env


def test_concurrent_backup_lock(tmp_path):
    from scripts.backup_database import _backup_lock

    with _backup_lock(tmp_path), pytest.raises(RuntimeError), _backup_lock(tmp_path):
        pytest.fail("second backup acquired the lock")
    assert not (tmp_path / ".s62.lock").exists()


def test_failed_mirror_does_not_prune_previous_backups(monkeypatch, tmp_path):
    import scripts.backup_database as backup

    directory, mirror = tmp_path / "backups", tmp_path / "mirror"
    directory.mkdir()
    previous = directory / "old.dump.enc"
    previous.write_bytes(b"previous")
    monkeypatch.setattr(backup, "BACKUP_DIR", directory)
    monkeypatch.setenv("S62_BACKUP_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@host/db")
    monkeypatch.setenv("S62_MIRROR_DIR", str(mirror))
    monkeypatch.setenv("S62_KEEP_COUNT", "1")

    def dump(args, env, **kwargs):
        kwargs["stdout"].write(b"custom dump")

    def fail(*args):
        raise OSError("remote unavailable")

    monkeypatch.setattr(backup, "_run", dump)
    monkeypatch.setattr(backup, "_mirror", fail)
    with pytest.raises(OSError):
        backup.create_backup()
    assert previous.read_bytes() == b"previous"
    assert not (directory / ".s62.lock").exists()


def test_restore_rejects_same_source_before_invoking_postgres(monkeypatch, tmp_path):
    import scripts.backup_database as backup

    monkeypatch.setenv("S62_BACKUP_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@host/db")
    monkeypatch.setenv("S62_RESTORE_DATABASE_URL", "postgresql://other@host/db")
    with pytest.raises(RuntimeError, match="differ"):
        backup.restore_backup(tmp_path / "not-needed")


def test_restore_requires_explicit_target(monkeypatch, tmp_path):
    import scripts.backup_database as backup

    monkeypatch.setenv("S62_BACKUP_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("S62_RESTORE_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="S62_RESTORE_DATABASE_URL"):
        backup.restore_backup(tmp_path / "not-needed")


def test_reject_legacy_format(tmp_path):
    archive = tmp_path / "legacy"
    archive.write_bytes(b"CSMSBK01")
    with pytest.raises(ValueError, match="v1"):
        decrypt_backup(archive, tmp_path / "output", Fernet.generate_key())


def test_timeout_is_a_failed_cli_without_connection_details(monkeypatch, capsys):
    import subprocess

    import scripts.backup_database as backup

    def fail():
        raise subprocess.TimeoutExpired("secret-connection", 10)

    monkeypatch.setattr(backup, "create_backup", fail)
    monkeypatch.setattr("sys.argv", ["backup_database.py", "backup"])
    assert backup.main() == 1
    assert "secret-connection" not in capsys.readouterr().err
