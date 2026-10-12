# T-106 / S-38 — Wallet denial on the driver start screen

Scope: T-106 in `Chia_viec_Sprint_4-5_hoan_thien.xlsx` and S-38 in
`Backlog CSMS.xlsx`. Preserve the contributor's UI and extend its actual API path.

## Contract

`POST /api/v1/driver/charging/start` returns HTTP 409 for an ineligible wallet:

```json
{"detail":{"reason":"wallet_low","balance_vnd":20000,"minimum_balance_vnd":22500}}
```

Other reasons remain `wallet_missing`, `wallet_locked`, `tariff_unavailable`.
Amounts can be null when unavailable; the UI never invents a zero or threshold.
Other HTTP 409 conflicts still use a string detail. The UI accepts legacy wallet
strings for compatibility, but numeric acceptance requires the updated backend.

If RemoteStart is accepted but StartTransaction fails eligibility, preserve
`reply_status=Accepted`, persist `status=Rejected`, `rejection_reason`, and both
amounts from the **same eligibility result** that denied the transaction.
Start/current/SSE responses include `connector_id`, `balance_vnd`, and
`minimum_balance_vnd`. Replay retains this rejection snapshot after funding;
the next attempt has a fresh request ID and performs a new eligibility check.

Migration `e190019a2026` adds two nullable BIGINT fields to driver_start_requests.
Run migrations before starting the updated backend. Existing rejection history
has null amounts; no reconstruction or money movement occurs. Downgrade removes
only these fields, so their snapshots are lost while request history remains.
Runtime table privileges continue to cover the new columns.

## UI

Keep the existing driver layout and four reason messages. Wallet-low adds
localized amounts labeled "Số dư lúc kiểm tra" / "Cần tối thiểu" and the existing
`#driver-wallet` link to the wallet/top-up area. Show delayed SSE wallet failures
instead of the generic charger rejection. Clear/dismiss failures on station or
connector changes; scope late POST responses to their original selection.
Wallet denial permits a new request after top-up; an uncertain network failure
still retains the idempotency key for a safe retry.

## Acceptance and evidence

- PostgreSQL/real WebSocket regression: initial funds through T-88 receipts at
  14,999 / 15,000 / 15,001 VND, threshold 15,000 VND. Authorize and StartTransaction
  block only below threshold. Below-threshold API returns both amounts without a
  request/session; T-88 +1 VND permits RemoteStart and StartTransaction, one session,
  wallet 15,000 equals ledger sum. No payment gateway is mocked as a real payment.
- Asynchronous rejection regressions check both command-reply races, current/SSE
  data and retained numeric snapshots after top-up. Existing ownership/auth tests
  remain in the focused backend suite.
- Migration round trip preserves rejection status/reply/reason; existing rows
  have null amounts after re-upgrade. BIGINT accepts values beyond 32-bit range.
- UI tests cover legacy/structured errors, numeric zero, delayed SSE, selection
  reset, fresh retry and actual backend-confirmed session navigation.
- Browser check of the production components at 360/1280px uses API fixtures for
  the wallet-low state and top-up navigation, with no horizontal overflow or JS
  exceptions. This is UI evidence, not a staging/gateway payment acceptance run.

Run:

```powershell
pytest tests/test_t106_real_ocpp.py tests/test_t106_wallet_snapshot_migration.py tests/test_wallet_start_integration.py tests/test_driver_charging.py tests/test_wallet_eligibility.py -q
npm --prefix frontend test -- src/features/driver/DriverCharging.test.tsx src/features/driver/DriverWorkspace.test.tsx
```

The original MeterValues performance gate remains unchanged. Run it separately
from the functional tests, following the existing CI workflow. PR/CI evidence
does not update Jira or deploy these changes to staging.
