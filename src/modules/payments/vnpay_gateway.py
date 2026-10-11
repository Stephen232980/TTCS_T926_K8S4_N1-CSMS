"""VNPAY PAY 2.1.0 sandbox: sorted, form-encoded query and HMAC-SHA512."""

import hashlib
import hmac
import ipaddress
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from pydantic import HttpUrl, SecretStr, ValidationError

from src.modules.payments.contracts import (
    GatewayEvent,
    InvalidWebhookPayload,
    InvalidWebhookSignature,
    PaymentGatewayUnavailable,
    PaymentRedirect,
    PaymentRequest,
)


class VnpayGateway:
    def __init__(
        self,
        *,
        tmn_code: str,
        secret: SecretStr,
        payment_url: str,
        return_url: HttpUrl,
        expiry_minutes: int = 15,
    ) -> None:
        self.tmn_code = tmn_code
        self._secret = secret
        self.payment_url = payment_url
        self.return_url = return_url
        self.expiry_minutes = expiry_minutes

    def _signature(self, params: Mapping[str, str]) -> str:
        encoded = urlencode(sorted(params.items()))
        return hmac.new(
            self._secret.get_secret_value().encode(), encoded.encode(), hashlib.sha512
        ).hexdigest()

    async def create_payment(self, request: PaymentRequest) -> PaymentRedirect:
        if request.amount_vnd * 100 > 999_999_999_999:
            raise PaymentGatewayUnavailable("VNPAY amount exceeds protocol limit")
        try:
            client_ip = str(ipaddress.ip_address(request.client_ip))
        except ValueError as exc:
            raise PaymentGatewayUnavailable("Payment client IP unavailable") from exc
        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        params = {
            "vnp_Version": "2.1.0",
            "vnp_Command": "pay",
            "vnp_TmnCode": self.tmn_code,
            "vnp_Amount": str(request.amount_vnd * 100),
            "vnp_CurrCode": "VND",
            "vnp_TxnRef": request.order_id,
            "vnp_OrderInfo": "Nap vi CSMS " + request.order_id,
            "vnp_OrderType": "other",
            "vnp_Locale": "vn",
            "vnp_ReturnUrl": str(self.return_url),
            "vnp_IpAddr": client_ip,
            "vnp_CreateDate": now.strftime("%Y%m%d%H%M%S"),
            "vnp_ExpireDate": (now + timedelta(minutes=self.expiry_minutes)).strftime(
                "%Y%m%d%H%M%S"
            ),
        }
        query = urlencode(sorted(params.items()))
        return PaymentRedirect(
            redirect_url=HttpUrl(
                self.payment_url
                + "?"
                + query
                + "&vnp_SecureHash="
                + self._signature(params)
            )
        )

    def verify_query(self, items: Sequence[tuple[str, str]]) -> GatewayEvent:
        # Reject ambiguity, including duplicated secure hashes, before normalization.
        params: dict[str, str] = {}
        for key, value in items:
            if key in params or not key.startswith("vnp_") or len(value) > 512:
                raise InvalidWebhookSignature("Ambiguous VNPAY parameters")
            params[key] = value
        supplied = params.pop("vnp_SecureHash", "")
        params.pop("vnp_SecureHashType", None)
        if not re.fullmatch(r"[0-9a-fA-F]{128}", supplied) or not hmac.compare_digest(
            self._signature(params), supplied.lower()
        ):
            raise InvalidWebhookSignature("Invalid VNPAY signature")
        try:
            if params["vnp_TmnCode"] != self.tmn_code:
                raise ValueError("Wrong merchant")
            if params.get("vnp_CurrCode", "VND") != "VND":
                raise ValueError("Wrong currency")
            amount = params["vnp_Amount"]
            code = params["vnp_ResponseCode"]
            state = params["vnp_TransactionStatus"]
            transaction = params["vnp_TransactionNo"]
            if not re.fullmatch(r"[0-9]{1,12}", amount) or int(amount) % 100:
                raise ValueError("Invalid integer VND amount")
            if not re.fullmatch(r"[0-9]{2}", code) or not re.fullmatch(
                r"[0-9]{2}", state
            ):
                raise ValueError("Invalid result")
            if not re.fullmatch(r"[0-9]{1,15}", transaction):
                raise ValueError("Invalid transaction")
            # Both success fields must agree; inconsistent data is never a credit.
            if (code == "00") != (state == "00"):
                raise ValueError("Conflicting result")
            succeeded = code == "00" and state == "00"
            if succeeded and int(transaction) == 0:
                raise ValueError("Missing successful transaction ID")
            order = params["vnp_TxnRef"]
            if not re.fullmatch(r"vnpay[0-9a-f]{32}", order):
                raise ValueError("Invalid order reference")
            # Unsuccessful attempts may carry TransactionNo=0; do not make all
            # failed orders collide on that sentinel in the database.
            reference = "vnpay:" + (
                str(int(transaction)) if int(transaction) else "failed:" + order
            )
            return GatewayEvent(
                order_id=order,
                amount_vnd=int(amount) // 100,
                gateway_transaction_id=reference,
                status="succeeded"
                if succeeded
                else "cancelled"
                if code == "24"
                else "failed",
                reason=None if succeeded else "VNPAY response " + code,
            )
        except (KeyError, ValueError, ValidationError) as exc:
            raise InvalidWebhookPayload("Invalid authenticated VNPAY result") from exc

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> GatewayEvent:
        # VNPAY is a GET IPN protocol, never the generic JSON webhook.
        raise InvalidWebhookPayload("Use the VNPAY IPN endpoint")
