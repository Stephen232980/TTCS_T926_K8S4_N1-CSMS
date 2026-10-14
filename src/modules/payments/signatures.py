"""Raw-body signature primitive for the T-92 fake gateway contract."""

import hashlib
import hmac
import re
from collections.abc import Mapping

from pydantic import SecretStr

from src.modules.payments.contracts import SIGNATURE_HEADER, InvalidWebhookSignature


def verify_hmac_sha256(
    raw_body: bytes, headers: Mapping[str, str], secret: SecretStr
) -> None:
    key = secret.get_secret_value()
    if not key.strip():
        raise ValueError("webhook secret must not be empty")
    signatures = [
        value
        for name, value in headers.items()
        if name.lower() == SIGNATURE_HEADER.lower()
    ]
    if (
        len(signatures) != 1
        or re.fullmatch(r"sha256=[0-9a-f]{64}", signatures[0]) is None
    ):
        raise InvalidWebhookSignature("invalid webhook signature")
    expected = (
        "sha256=" + hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(signatures[0], expected):
        raise InvalidWebhookSignature("invalid webhook signature")
