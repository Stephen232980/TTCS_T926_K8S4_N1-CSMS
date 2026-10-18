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


def test_prune_backups_keeps_latest_14(tmp_path: Path) -> None:
    import os

    backups = []
    for index in range(16):
        path = tmp_path / f"backup-{index:02}.dump.enc"
        path.write_bytes(b"backup")
        timestamp = 1_800_000_000 + index
        os.utime(path, (timestamp, timestamp))
        backups.append(path)

    prune_backups(tmp_path, keep=14)

    remaining = sorted(tmp_path.glob("*.dump.enc"))
    assert len(remaining) == 14
    assert [path.name for path in remaining] == [
        f"backup-{index:02}.dump.enc" for index in range(2, 16)
    ]
