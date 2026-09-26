from src.modules.identity.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_dummy_password,
    verify_password,
)


def test_password_is_hashed_with_argon2id() -> None:
    password_hash = hash_password("mat-khau-bi-mat")

    assert password_hash.startswith("$argon2id$")
    assert "mat-khau-bi-mat" not in password_hash


def test_correct_password_is_accepted() -> None:
    password_hash = hash_password("mat-khau-dung")

    assert verify_password(password_hash, "mat-khau-dung") is True


def test_wrong_password_is_rejected() -> None:
    password_hash = hash_password("mat-khau-dung")

    assert verify_password(password_hash, "mat-khau-sai") is False


def test_invalid_password_hash_is_rejected() -> None:
    assert verify_password("khong-phai-argon2-hash", "mat-khau") is False


def test_dummy_password_verification_does_not_raise_error() -> None:
    verify_dummy_password("bat-ky-mat-khau-nao")


def test_session_token_is_random() -> None:
    first_token = generate_session_token()
    second_token = generate_session_token()

    assert first_token != second_token
    assert len(first_token) >= 32


def test_session_token_hash_is_sha256_hex() -> None:
    token = generate_session_token()
    token_hash = hash_session_token(token)

    assert len(token_hash) == 64
    assert token_hash != token
    assert token_hash == hash_session_token(token)
