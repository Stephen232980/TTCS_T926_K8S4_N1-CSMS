# S-39 / T-96: database webhook idempotency

PR #112 integrates the T-95 settlement contract from merged PR #117. The single
runtime handler remains `process_topup_webhook(session, event)`. No separate
wallet-credit path, memory flag, schema change or migration is introduced.

## Guarantees

- Order `SELECT FOR UPDATE` serializes callbacks until commit/rollback.
  `populate_existing=True` refreshes the status after acquiring the lock.
- A matching successful replay returns HTTP 200 before ledger, balance or order
  writes. It does not change `updated_at` or recheck a wallet for a new credit.
- `uq_wallet_topups_gateway` provides a global gateway transaction key across orders.
- `uq_wallet_ledger_reference` provides global `(entry_type, reference_id)` uniqueness.
- Different orders racing for one gateway ID have one database winner; the other
  is marked needs_review after savepoint rollback without a second credit or 500.
- Raw-byte signature, amount validation, T-95 state table and rollback remain intact.
  A duplicate cannot bypass signature checks or alter credited money.
- No request is acknowledged until the route commits. A failure before commit
  leaves the order pending and can be retried with the same signed callback.

## Acceptance evidence

`tests/test_t96_webhook_idempotency.py` uses the actual public HTTP route and an
isolated PostgreSQL database, with committed orders and wallets:

1. Five identical signed success callbacks all return 200; one ledger row and
   one balance increase; order `updated_at` is unchanged after the first callback.
2. Two success requests use distinct `pg_backend_pid()` values. The first is held
   after flushing its credit; an observer confirms `pg_blocking_pids(second)`
   contains the first PID before release. Both return 200 and only one credit runs.
3. Two different wallets/orders concurrently reuse a gateway ID: one credit,
   one succeeded order, one needs_review order, one stored gateway transaction ID.
4. A failure after credit flush but before route commit rolls everything back;
   retry plus replay produces one committed credit.
5. Five failed callbacks and five cancelled callbacks never credit.
6. Tampered raw bytes return 401; a re-signed mismatched amount returns 400 and
   cannot downgrade an already succeeded order or change its money.

Synchronization events exist only in tests to observe overlapping requests; runtime
idempotency is entirely in PostgreSQL. Fixtures retain append-only ledger records;
no ledger trigger is disabled. No staging or multi-process HTTP load claim is made.

## Team integration

Keep member commits and merge history in this PR. T-97 still owns complete warning
aggregation/error acceptance; T-98 still needs its full assigned acceptance checked.
T-94 can use the existing T-93 GET order status, which reads committed state.
