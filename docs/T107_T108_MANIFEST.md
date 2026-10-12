# T-107 ↔ T-108 run manifest (PR #135 contract)

Shared source files `simulator/t108_contract.py` and `simulator/t108_fixture.py` are now included in PR #133, extracted from PR #135. They are the canonical common contract/fixture; no T-108 runner or spreadsheet/report orchestration is included here. Docker backend packages these modules so the manifest CLI works in the deployed image. Merge #133 first, then merge develop into #135 and reuse these modules; do not maintain divergent schemas or rewrite contributor history.

T-108 creates the station/chargers/connectors and initial tariff for each distinct run via `prepare_station`; persist its manifest JSON including `tariff_id`. T-107 uses `scripts.t107_manifest_run` to validate that these resources already exist, and then delegates driver, card, wallet, ledger and T-88 receipt provisioning to the shared `seed_manifest` adapter. The adapter still contains a defensive `prepare_station()` call: because T-107 has prevalidated the exact existing resources, this is a revalidation of the existing tariff, **not creation of a new one** for the CLI path.

- One run, one UUID namespace; receipt codes are `T108-<run-id>-NNN` and never shared between runs.
- Retry uses existing receipts rather than refill/debit reset. `pg_advisory_xact_lock` serializes same-run seed and cleanup; keep all operations within `session.begin()`.
- Never seed a cleaned run again; instead start with a new `run_id`.
- Cleanup blocks open/unsettled sessions and preserves billing/ledger/audit. It archives only the manifest-scoped fixture.

## Local isolated test database

Verify `DATABASE_URL` points at the isolated test database, not local demo/staging/production. `T107_ALLOW_STAGING_SEED=YES` and `--confirm-test-environment` are both required for writes.

```powershell
$env:T107_ALLOW_STAGING_SEED="YES"
.\.venv\Scripts\python.exe -m scripts.t107_manifest_run --manifest .\path\run.json --apply --admin-email seed-admin-t107@example.com --confirm-test-environment
.\.venv\Scripts\python.exe -m scripts.t107_manifest_run --manifest .\path\run.json --cleanup --confirm-test-environment
.\.venv\Scripts\python.exe -m pytest -q tests/test_t107_manifest_run.py tests/test_t107_manifest_postgres.py tests/test_t107_staging_seed.py tests/test_t107_tariff_seed.py
.\.venv\Scripts\python.exe -m ruff check scripts/t107_manifest_run.py simulator/t108_contract.py simulator/t108_fixture.py tests/test_t107_manifest_run.py
.\.venv\Scripts\python.exe -m ruff format --check scripts/t107_manifest_run.py simulator/t108_contract.py simulator/t108_fixture.py tests/test_t107_manifest_run.py
```

Do not apply this script to an old `T107-STAGING-VIRTUAL-STATION` fixture; the old fixed-fixture seed/cleanup CLI is blocked. T-108 prepares a new station/three-band tariff and persists its manifest including tariff_id before T-107 apply. Cleanup is logical archival, preserving financial history; the isolated namespace is separate from real users and S-26 fixtures.

## Evidence

Historical verification reported by the initial integration patch:

- Ruff lint: passed.
- Ruff format check: passed.
- Unit tests: 31 passed.
- PostgreSQL integration: 2 passed using an isolated PostgreSQL server.
- Docker backend image: `docker compose build app` succeeded.
- Legacy fixed-fixture CLI: both `--apply` and `--cleanup` are blocked.
- One pytest-asyncio deprecation warning remains; tests pass.

The updated PostgreSQL tests seed two runs of **20 drivers each**, concurrent same-run retry and per-run T-88 receipts/audits, preserve balances after debit, cleanup one run while retaining the other, rollback a conflict on driver 10 after earlier funding writes, and refuse cleanup of open/ended-unsettled sessions with no partial archival. Manifest tests reject altered identities and enforce 20 participants in staging mode. Initial verification numbers above are historical; validate CI on the latest head before merge.

The common modules ship with #133; T-107 no longer imports files absent from its branch. T-108 still owns station orchestration and three-run end-to-end reconciliation; that scope remains in #135.

These results are local verification only. GitHub CI, staging deployment, and end-to-end staging verification have not yet been confirmed.
