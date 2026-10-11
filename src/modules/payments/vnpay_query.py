"""Signed QueryDR responses are separate from PAY/IPN query signatures."""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from src.modules.payments.contracts import (
    GatewayEvent,
    InvalidWebhookPayload,
    InvalidWebhookSignature,
)
from src.modules.payments.vnpay_gateway import VnpayGateway

QUERY_URL = "https://sandbox.vnpayment.vn/merchant_webapi/api/transaction"
REQUEST_FIELDS = (
    "vnp_RequestId",
    "vnp_Version",
    "vnp_Command",
    "vnp_TmnCode",
    "vnp_TxnRef",
    "vnp_TransactionDate",
    "vnp_CreateDate",
    "vnp_IpAddr",
    "vnp_OrderInfo",
)
RESPONSE_FIELDS = (
    "vnp_ResponseId",
    "vnp_Command",
    "vnp_ResponseCode",
    "vnp_Message",
    "vnp_TmnCode",
    "vnp_TxnRef",
    "vnp_Amount",
    "vnp_BankCode",
    "vnp_PayDate",
    "vnp_TransactionNo",
    "vnp_TransactionType",
    "vnp_TransactionStatus",
    "vnp_OrderInfo",
    "vnp_PromotionCode",
    "vnp_PromotionAmount",
)


def query_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10, follow_redirects=False)


def signature(
    adapter: VnpayGateway, fields: tuple[str, ...], data: dict[str, str]
) -> str:
    # QueryDR uses fixed field order and pipes, not sorted URL encoding.
    value = "|".join(data.get(field, "") for field in fields)
    return hmac.new(
        adapter._secret.get_secret_value().encode(), value.encode(), hashlib.sha512
    ).hexdigest()


def unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise InvalidWebhookPayload("Duplicate QueryDR field")
        result[key] = value
    return result


@dataclass(frozen=True)
class QueryResult:
    request_id: str
    response_code: str
    transaction_status: str | None
    event: GatewayEvent | None


async def query_transaction(
    adapter: VnpayGateway, order: str, transaction_date: str, server_ip: str
) -> QueryResult:
    request = {
        "vnp_RequestId": uuid4().hex,
        "vnp_Version": "2.1.0",
        "vnp_Command": "querydr",
        "vnp_TmnCode": adapter.tmn_code,
        "vnp_TxnRef": order,
        "vnp_TransactionDate": transaction_date,
        "vnp_CreateDate": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime(
            "%Y%m%d%H%M%S"
        ),
        "vnp_IpAddr": server_ip,
        "vnp_OrderInfo": "Doi soat nap vi CSMS " + order,
    }
    request["vnp_SecureHash"] = signature(adapter, REQUEST_FIELDS, request)
    # Fixed provider URL, bounded response, no redirects or signed payload logging.
    async with (
        query_client() as client,
        client.stream("POST", QUERY_URL, json=request) as response,
    ):
        response.raise_for_status()
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw) > 32768:
                raise InvalidWebhookPayload("QueryDR response too large")
    data = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(data, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) or len(v) > 512
        for k, v in data.items()
    ):
        raise InvalidWebhookPayload("Invalid QueryDR response")
    supplied = data.get("vnp_SecureHash", "")
    if not re.fullmatch(r"[a-fA-F0-9]{128}", supplied) or not hmac.compare_digest(
        signature(adapter, RESPONSE_FIELDS, data), supplied.lower()
    ):
        raise InvalidWebhookSignature("Invalid QueryDR signature")
    if (
        data.get("vnp_TmnCode") != adapter.tmn_code
        or data.get("vnp_TxnRef") != order
        or data.get("vnp_Command") != "querydr"
    ):
        raise InvalidWebhookPayload("QueryDR response identity mismatch")
    if not re.fullmatch(r"[A-Za-z0-9]{1,32}", data.get("vnp_ResponseId", "")):
        raise InvalidWebhookPayload("Invalid QueryDR response ID")
    code = data.get("vnp_ResponseCode", "")
    if not re.fullmatch(r"[0-9]{2}", code):
        raise InvalidWebhookPayload("Invalid QueryDR response code")
    if code != "00":
        # Includes 91 (not found) and 94 (rate limit); neither proves failure.
        return QueryResult(request["vnp_RequestId"], code, None, None)
    amount = data.get("vnp_Amount", "")
    state = data.get("vnp_TransactionStatus", "")
    transaction = data.get("vnp_TransactionNo", "")
    if (
        data.get("vnp_TransactionType") != "01"
        or not re.fullmatch(r"[0-9]{1,12}", amount)
        or int(amount) <= 0
        or int(amount) % 100
        or not re.fullmatch(r"[0-9]{2}", state)
        or not re.fullmatch(r"[0-9]{1,15}", transaction)
    ):
        raise InvalidWebhookPayload("Invalid QueryDR transaction")
    if state not in {"00", "02"}:
        # Unfinished, reversal/refund/fraud need investigation, not a wallet write.
        return QueryResult(request["vnp_RequestId"], code, state, None)
    if state == "00" and int(transaction) == 0:
        raise InvalidWebhookPayload("Missing successful QueryDR transaction")
    event = GatewayEvent(
        order_id=order,
        amount_vnd=int(amount) // 100,
        gateway_transaction_id="vnpay:"
        + (str(int(transaction)) if int(transaction) else "failed:" + order),
        status="succeeded" if state == "00" else "failed",
        reason=None if state == "00" else "VNPAY QueryDR transaction status 02",
    )
    return QueryResult(request["vnp_RequestId"], code, state, event)
