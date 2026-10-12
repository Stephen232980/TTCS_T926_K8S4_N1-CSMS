# T-107 ↔ T-108 run manifest (PR #135 contract)

Shared source files: `simulator/t108_contract.py` and `simulator/t108_fixture.py` are **byte-identical copies of PR #135** in this integration patch. They MUST have **one canonical owner**: coordinate PR #135 to reuse/remove the duplicate additions before merging, or merge PR #135 first and rebase T-107 to use the existing versions. Do not maintain divergent schemas.

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
.\.venv\Scripts\python.exe -m pytest -q tests/test_t107_manifest_run.py tests/test_t108_acceptance.py
.\.venv\Scripts\python.exe -m ruff check scripts/t107_manifest_run.py simulator/t108_contract.py simulator/t108_fixture.py tests/test_t107_manifest_run.py
.\.venv\Scripts\python.exe -m ruff format --check scripts/t107_manifest_run.py simulator/t108_contract.py simulator/t108_fixture.py tests/test_t107_manifest_run.py
```

Do not apply this script to an old `T107-STAGING-VIRTUAL-STATION` fixture; the old fixed-fixture path is legacy test-only. T-108 manifest path is separate. The user should verify what the T-108 CLI actually produces before running T-107. The shared adapter's extra validations and DB integration tests are pending final code-owner coordination.

## Evidence

Local verification completed on the T-107 integration branch:

- Ruff lint: passed.
- Ruff format check: passed.
- Unit tests: 31 passed.
- PostgreSQL integration: 2 passed using an isolated PostgreSQL server.
- Docker backend image: `docker compose build app` succeeded.
- Legacy fixed-fixture CLI: both `--apply` and `--cleanup` are blocked.
- One pytest-asyncio deprecation warning remains; tests pass.

The PostgreSQL integration tests cover two isolated runs, concurrent retry, per-run receipt idempotency, balance preservation after a debit, cleanup isolation, and rejection of a mismatched manifest without wallet ledger writes.

The shared T-108 contract and fixture files are byte-identical to PR #135. T-108 owns these modules; T-107 depends on their availability.

These results are local verification only. GitHub CI, staging deployment, and end-to-end staging verification have not yet been confirmed.
