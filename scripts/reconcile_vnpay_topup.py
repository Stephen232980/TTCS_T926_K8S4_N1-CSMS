"""Interactive administrator client; --help never logs in or changes orders."""

import argparse
import getpass
import json
import re

import httpx

BASE_URL = "https://csms-staging.daominhtam2k6.id.vn"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query VNPAY through the audited administrator API. Default: preview only."
    )
    parser.add_argument("--order", required=True)
    parser.add_argument(
        "--transaction-date",
        help="Original vnp_CreateDate, GMT+7, for legacy orders only",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply verified provider result through shared settlement",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"vnpay[0-9a-f]{32}", args.order):
        parser.error("Expected a CSMS VNPAY order reference")
    email = input("Administrator email: ").strip()
    password = getpass.getpass("Administrator password (hidden): ")
    body: dict[str, object] = {"apply": args.apply}
    if args.transaction_date:
        body["transaction_date"] = args.transaction_date
    with httpx.Client(base_url=BASE_URL, timeout=20, follow_redirects=False) as client:
        logged_in = False
        try:
            response = client.post(
                "/api/v1/auth/login", json={"email": email, "password": password}
            )
            password = ""
            if response.status_code != 200:
                raise SystemExit("Login failed; no reconciliation requested.")
            logged_in = True
            response = client.post(
                "/api/v1/admin/payments/vnpay/topups/" + args.order + "/reconcile",
                json=body,
            )
            if response.status_code != 200:
                raise SystemExit(
                    f"Reconciliation returned HTTP {response.status_code}; check provider/configuration and retry preview."
                )
            result = response.json()
            # Print only the administrator API's safe result, never cookies/provider hashes.
            allowed = (
                "order_id",
                "status",
                "query_response_code",
                "transaction_status",
                "transaction_date",
                "request_id",
                "applied",
                "requires_review",
                "amount_vnd",
            )
            print(json.dumps({k: result.get(k) for k in allowed}, ensure_ascii=False))
        except httpx.HTTPError:
            raise SystemExit(
                "Connection failed; query status again before retrying apply."
            ) from None
        finally:
            if logged_in:
                try:
                    client.post("/api/v1/auth/logout")
                except httpx.HTTPError:
                    print(
                        "Session logout could not be confirmed; revoke the administrator session if needed."
                    )


if __name__ == "__main__":
    main()
