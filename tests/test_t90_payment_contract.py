import hashlib
import hmac

import pytest
from pydantic import SecretStr, ValidationError

from src.config import Settings
from src.modules.payments.contracts import (
    GatewayEvent,
    InvalidWebhookSignature,
    PaymentRedirect,
    PaymentRequest,
)
from src.modules.payments.signatures import verify_hmac_sha256

BODY = b'{"gateway_transaction_id":"fake-tx-1","order_id":"topup-1","amount_vnd":100000,"status":"succeeded"}'
SECRET = SecretStr("test-only-private-key")


def settings(**values):
    return Settings(
        _env_file=None, database_url="postgresql+psycopg://unused", **values
    )


@pytest.fixture(autouse=True)
def isolated_payment_environment(monkeypatch):
    for name in ("PAYMENT_GATEWAY", "PAYMENT_WEBHOOK_SECRET", "PAYMENT_RETURN_URL"):
        monkeypatch.delenv(name, raising=False)


def test_disabled_default_preserves_existing_app_configuration():
    configured = settings()
    assert configured.payment_gateway == "disabled"
    assert configured.payment_webhook_secret is None
    assert (
        str(configured.payment_return_url)
        == "http://localhost:5173/wallet/topup/return"
    )


def test_configuration_reads_three_environment_variables_and_masks_secret(monkeypatch):
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "private-test-value")
    monkeypatch.setenv(
        "PAYMENT_RETURN_URL", "https://frontend.example/wallet/topup/return"
    )
    configured = settings()
    assert configured.payment_gateway == "fake"
    assert configured.payment_webhook_secret.get_secret_value() == "private-test-value"
    assert str(configured.payment_return_url).startswith("https://frontend.example/")
    assert "private-test-value" not in repr(configured)
    assert "private-test-value" not in configured.model_dump_json()


@pytest.mark.parametrize("gateway", ["fake", "sandbox"])
@pytest.mark.parametrize("secret", [None, "", "   "])
def test_enabled_gateway_requires_nonempty_secret(gateway, secret):
    with pytest.raises(ValidationError):
        settings(payment_gateway=gateway, payment_webhook_secret=secret)


def test_unknown_gateway_rejected():
    with pytest.raises(ValidationError):
        settings(payment_gateway="typo")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://user:pass@example.com/",
        "https://example.com/#fragment",
    ],
)
def test_unsafe_urls_rejected_in_settings_and_contract(url):
    with pytest.raises(ValidationError):
        settings(payment_return_url=url)
    with pytest.raises(ValidationError):
        PaymentRequest(order_id="order", amount_vnd=100000, return_url=url)
    with pytest.raises(ValidationError):
        PaymentRedirect(redirect_url=url)


@pytest.mark.parametrize("amount", [0, -1, True, 100000.0, "100000", 2**63])
def test_money_is_positive_bigint_without_coercion(amount):
    with pytest.raises(ValidationError):
        GatewayEvent(
            gateway_transaction_id="tx",
            order_id="order",
            amount_vnd=amount,
            status="succeeded",
        )
    with pytest.raises(ValidationError):
        PaymentRequest(
            order_id="order", amount_vnd=amount, return_url="https://example.com/return"
        )


@pytest.mark.parametrize("identifier", ["", " ", " order", "order\n", "x" * 129])
def test_invalid_identifiers_rejected(identifier):
    with pytest.raises(ValidationError):
        GatewayEvent(
            gateway_transaction_id=identifier,
            order_id=identifier,
            amount_vnd=100000,
            status="succeeded",
        )


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_gateway_events_match_wallet_terminal_statuses(status):
    event = GatewayEvent(
        gateway_transaction_id="tx-1",
        order_id="order-1",
        amount_vnd=100000,
        status=status,
    )
    assert event.amount_vnd == 100000 and event.status == status
    with pytest.raises(ValidationError):
        event.amount_vnd = 200000


@pytest.mark.parametrize("status", ["pending", "needs_review", "success"])
def test_internal_or_unknown_status_not_a_terminal_gateway_event(status):
    with pytest.raises(ValidationError):
        GatewayEvent(
            gateway_transaction_id="tx", order_id="order", amount_vnd=1, status=status
        )


def signature():
    return (
        "sha256="
        + hmac.new(SECRET.get_secret_value().encode(), BODY, hashlib.sha256).hexdigest()
    )


def test_signature_uses_exact_bytes_and_case_insensitive_header():
    verify_hmac_sha256(BODY, {"x-payment-signature": signature()}, SECRET)
    with pytest.raises(InvalidWebhookSignature):
        verify_hmac_sha256(BODY + b" ", {"X-Payment-Signature": signature()}, SECRET)
    with pytest.raises(InvalidWebhookSignature):
        verify_hmac_sha256(
            BODY, {"X-Payment-Signature": signature()}, SecretStr("wrong")
        )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Payment-Signature": "bad"},
        {"X-Payment-Signature": "sha256=" + "0" * 64},
        {"X-Payment-Signature": "sha256=" + "A" * 64},
    ],
)
def test_signature_errors_do_not_echo_request_or_signature(headers):
    with pytest.raises(InvalidWebhookSignature, match="^invalid webhook signature$"):
        verify_hmac_sha256(BODY, headers, SECRET)


def test_duplicate_signature_headers_rejected():
    with pytest.raises(InvalidWebhookSignature):
        verify_hmac_sha256(
            BODY,
            {"X-Payment-Signature": signature(), "x-payment-signature": signature()},
            SECRET,
        )


def test_empty_verification_key_is_configuration_error():
    with pytest.raises(ValueError, match="secret must not be empty"):
        verify_hmac_sha256(BODY, {}, SecretStr(""))


def test_authenticated_example_matches_event_schema():
    verify_hmac_sha256(BODY, {"X-Payment-Signature": signature()}, SECRET)
    event = GatewayEvent.model_validate_json(BODY)
    assert event.order_id == "topup-1"
    assert event.gateway_transaction_id == "fake-tx-1"


def test_configuration_validation_error_does_not_print_secret():
    with pytest.raises(ValidationError) as caught:
        settings(payment_gateway="typo", payment_webhook_secret="private-test-value")
    assert "private-test-value" not in str(caught.value)
