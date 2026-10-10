# S-35 / T-95: signed top-up webhook settlement

## Scope and contract

POST `/api/v1/payments/webhook` is public and authenticates the exact request bytes
using the configured gateway's HMAC verifier. No user session/cookie is required.
Missing/invalid signatures return 401 before JSON parsing; malformed authenticated
payloads return 400. An unavailable/disabled adapter returns 503 and never credits.

The existing order is locked in PostgreSQL. Amounts must match exactly. Successful
pending orders call `ghi_so_cai` with `entry_type=gateway_topup`,
`reference_type=gateway_transaction`, `reference_id=gateway_transaction_id`.
The order, ledger and cached wallet balance commit together before HTTP acknowledgement.
Failed/cancelled orders record a reason and never credit.

Response: `{ "status": "<persisted status or not_found>", "received": true|false }`.
Unknown order: 404. Amount mismatch: 400, persisted needs_review unless already
successful. Domain/transaction-reference conflicts: 200, persisted needs_review,
no partial credit. A savepoint rolls back ledger/balance/order changes before
recording review in the still-valid outer transaction. Unexpected database faults
propagate and roll back; they are not acknowledged as successful settlement.

No new migration. Existing T-91 order/gateway uniqueness and T-86 immutable ledger
constraints remain enabled. Logs exclude webhook bodies, signatures, secrets and
untrusted gateway reason strings; review warnings use internal topup IDs and fixed reasons.

## State table (required by T-95, shared with T-97)

| Current | succeeded event | failed event | cancelled event |
|---|---|---|---|
| pending | succeeded, credit | failed, no credit | cancelled, no credit |
| succeeded | keep succeeded | keep succeeded | keep succeeded |
| failed | needs_review, no credit | keep failed | keep failed |
| cancelled | needs_review, no credit | keep cancelled | keep cancelled |
| needs_review | keep needs_review | keep needs_review | keep needs_review |

Amount and transaction identity checks precede transitions. An already successful
order is never downgraded. Review is not automatically resolved by another callback.

## Handoff to T-96 / PR #112

Use `src.modules.wallet.topup_webhook_service.process_topup_webhook(session, event)`
and this route as the single settlement path; do not add a second crediting handler.
The service owns no commits. The route owns commit/acknowledgement. Do not raise an
HTTP exception after recording review without committing that review.

Retain the state table and raw-byte authentication. Use the existing database unique
keys and order lock; do not use process-memory flags. Extend with acceptance tests
for five replays, two concurrent requests on separate sessions, cross-order reuse of
a gateway transaction and transaction rollback. Adapter replay and serial replay
already have baseline coverage here; this does not declare T-96/T-98 complete.
T-97 still owns complete warning aggregation and error acceptance. Review all
transition branches before enabling settlement on staging; this PR does not deploy.

## Validation

Run migrations against an isolated PostgreSQL database, then Ruff, mypy and pytest.
`tests/test_t95_webhook_settlement.py` covers all 15 transition cells, invalid
signature before JSON, unknown order, amount mismatch persisted across sessions,
real ledger/unique conflicts, rollback after a credit flush, wallet lock/overflow,
disabled adapter and success/replay/failure preserving one credit.
The T-93 integration test now creates an actual order, opens the signed fake payment
page, dispatches the callback and verifies a committed credit and one ledger row.
Committed fixtures retain immutable ledger data in the isolated test database;
no append-only trigger is disabled for cleanup.
