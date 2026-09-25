import pytest
from pydantic import ValidationError

from src.modules.identity.schemas import LoginRequest, LoginResponse


def test_login_request_accepts_valid_data() -> None:
    request = LoginRequest(
        email="owner@example.com",
        password="mat-khau-bi-mat",
    )

    assert str(request.email) == "owner@example.com"
    assert request.password.get_secret_value() == "mat-khau-bi-mat"


def test_login_request_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(
            email="email-khong-hop-le",
            password="mat-khau",
        )


def test_login_request_rejects_empty_password() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(
            email="owner@example.com",
            password="",
        )


def test_login_request_hides_password_in_representation() -> None:
    request = LoginRequest(
        email="owner@example.com",
        password="mat-khau-bi-mat",
    )

    assert "mat-khau-bi-mat" not in repr(request)


def test_login_response_has_authenticated_status() -> None:
    response = LoginResponse()

    assert response.status == "authenticated"
