# T-107 — Staging seed (implementation checkpoint)

## Current entry point after manifest integration

Use `python -m scripts.t107_manifest_run --manifest <run.json>` with `--apply
--admin-email <existing-test-admin>` or `--cleanup`, plus `--confirm-test-environment`
and `T107_ALLOW_STAGING_SEED=YES`. See `T107_T108_MANIFEST.md` for the current contract.
The shared modules are included in #133 and in the Docker backend. T-108 prepares
fresh station/chargers/tariff first; T-107 validates the saved manifest and funds
exactly its participants via T-88. Same-run retry never tops up again.

The phase descriptions and fixed-fixture commands below are historical context.
The `t107_staging_seed --apply/--cleanup` CLI is blocked; do not use those commands
for the current staging acceptance. Tests for the old helpers are retained to
preserve the contributor's work. Logical cleanup keeps financial/audit history.

## Verified scope (Sprint 4–5 assignment, row 38)

- S-37, owner TV2, reviewer TV6; dependencies T-59, T-84, T-55, T-88.
- 20 virtual drivers with cards and wallets; one 3-band tariff for virtual station(s).
- Fund wallet via T-88 administrative manual top-up, never direct balance edits.
- Use an isolated prefix, be idempotent, and supply a one-command cleanup.

## Phase 1 — safe first-tariff module

`scripts/t107_tariff_seed.py` contains strict, parameterized 3-band definitions,
uses the shared T-65 validator and T-66 creation service, and only targets a
pre-existing, dedicated **T107-** station. No tariff is modified in place.
The first version must become effective **today in station local time**, per
T-68. A second run returns its original ID only if all fields match, even if
the original tariff is now effective or used; no rows are modified. For T-108 each fresh simulated station will need its own first tariff,
with a boundary three minutes after the test begins.

This module alone only provides the tariff step. The Phase 2 seed below
creates a separate, prefixed virtual fleet and funds wallets via T-88; it does
not change the existing S-26 simulator behavior.

Example plan (illustrative rates, not approved business tariff):

```powershell
python -m scripts.t107_tariff_seed --boundaries 720 735 --rates 2000 3000 2500
```

Run `--apply --station-id <UUID>` **only on a dedicated staging test database**
after verifying the station name starts `T107-` and the values have been approved.

## Critical cleanup constraint

T-84/T-86 ledger and T-57 audit records are PostgreSQL append-only with DELETE
and TRUNCATE blocked. T-88 writes both and ties the wallet and the admin actor
to their immutable history. Therefore an automated hard-delete cleanup of
funded wallets/users is not compatible with the database invariants.

Design decision required from the team: one-command **logical cleanup**
(disable only prefixed test identities, cards and archive unused test stations;
retain immutable ledger/audit), or use a **dedicated disposable staging database**
whose entire database can be destroyed by the environment owner. Never bypass
triggers, cascade-delete ledgers, or run a cleanup against shared staging.

## Source review — S-26 simulator integration

The additional `simulator/` and Compose sources have now been reviewed. S-26
already creates `simulator-driver-*` users, virtual charging points, RFID
cards and wallets, but its wallet seeding uses `gateway_topup` ledger entries.
T-107 must instead use the T-88 administrative receipt flow, so it uses a
**separate `T107-` namespace**, without mutating the S-26 seed.

## Phase 2 — Dedicated test fleet (review candidate)

After reviewing `simulator/seed.py` and Compose, the T-107 seed deliberately
**does not run or modify S-26's seed**. S-26 uses `SIM-` chargers and
`simulator-driver-*` emails, and credits wallets via a `gateway_topup` ledger
entry. T-107 needs a separate namespace and specifically **T-88** manual topups.

`scripts/t107_staging_seed.py` implements a dedicated, atomic 20-driver fixture:

- One `T107-STAGING-VIRTUAL-STATION` owned by a dedicated `t107-seed-owner` test
  account, plus `T107-001` ... `T107-020` with one connector each.
- Twenty `t107-seed-driver-001` ... `020` test identities, unique `T107TAG-###`
  cards and provisioned wallets; generated credentials are random and **never
  printed**. The test owner is assigned `station_owner` and `operator` roles.
- First version of a three-band tariff through the Phase 1 shared service.
  Existing tariff versions are checked, never overwritten.
- Exactly one T-88 topup per wallet using the existing active administrator,
  `nap_tay` and stable receipts `T107-SEED-001` ... `020`. This writes the
  canonical wallet ledger and audit together. Repeats check wallet/receipt,
  do not top up again, and do not reset a wallet after testing debits.
- Transaction-scoped PostgreSQL advisory lock to serialize seed versus
  cleanup. Any unexpected existing owner/card/charger/receipt causes a clear
  failure, **rolling back the whole invocation**.

**Requirements:** All migrations deployed, configured 3-band rates and funding
approved by the project team, existing active admin login, and an explicitly
verified *isolated* PostgreSQL test database. Nothing should be written to a
production database or shared demo DB. Do not use the app's ordinary demo
credentials in public documentation.

### Plan-only dry run (never opens a database)

The numbers below are **illustrative only**. They are not approved tariff
prices; use the actual test rates and funding once your reviewer confirms.

```powershell
.\.venv\Scripts\python.exe -m scripts.t107_staging_seed --boundaries 720 735 --rates 2000 3000 2500 --amount-vnd 100000
```

### Write fixture (isolated test database ONLY)

Configure `DATABASE_URL` to point to the dedicated test DB and verify the
connection target out of band first. `T107_ALLOW_STAGING_SEED=YES` is a deliberate
acknowledgement, **not** a technical production guard. Example syntax:

```powershell
$env:T107_ALLOW_STAGING_SEED = 'YES'
.\.venv\Scripts\python.exe -m scripts.t107_staging_seed --boundaries 720 735 --rates 2000 3000 2500 --amount-vnd 100000 --admin-email <existing-active-test-admin-email> --confirm-test-environment --apply
```

Rerun that same command after the initial seed. Expect 20 receipts on the first
run and **0 new receipts** on the second run; verify the 20 card+driver+wallet
links in the database. Changing amount or rates on a rerun must fail closed.
One-time funding also checks the charging eligibility threshold at seed time;
subsequent charging can legitimately reduce balances without prompting refill.

### One-command logical cleanup (ONLY on the same isolated test DB)

```powershell
.\.venv\Scripts\python.exe -m scripts.t107_staging_seed --cleanup --confirm-test-environment
```

The env acknowledgement remains required. Cleanup checks fixture ownership
and refuses to proceed with open or unsettled test sessions. It deactivates
20 prefixed test driver users and the test owner, blocks 20 test cards, and
archives 20 chargers/connectors plus their station. **It does not delete**
users, wallets, tariffs, ledger rows, charging sessions, invoices or audit
logs; those records remain for referential integrity and accounting evidence.
A second cleanup is a no-op. Re-seeding after cleanup is intentionally refused:
use a fresh isolated database (or request a new fixture generation) rather
than rewriting historical evidence.

### Verification status / limitations

The contract/unit tests in `tests/test_t107_staging_seed.py` do **not** write
to a database. PostgreSQL acceptance must still validate the first seed,
idempotent second seed, 20 wallets with 20 T-88 receipts and audits, eligibility,
cleanup, protection of non-T107 records, and fail-closed behavior with a live
session. No actual staging execution or PostgreSQL acceptance is claimed.

**Open T-108 dependency:** its fresh virtual stations and run-specific
three-minute tariff boundary still require orchestration from T-108. This
fixture is a reusable staging starting point, not a replacement for the T-108
end-to-end 20-session settlement scenario.
