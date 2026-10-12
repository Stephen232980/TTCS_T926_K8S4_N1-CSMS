# T-108 / S-37: twenty-charger staging reconciliation

## Scope and acceptance matrix

Source: S-37 in `Backlog CSMS.xlsx` and T-108/T-107 in
`Chia_viec_Sprint_4-5_hoan_thien.xlsx`. Task evidence is separate from Jira status
and TV6's story acceptance. No API/schema or production settlement code changes.

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Fresh station and first tariff each run | UUID namespace, T-66 creation, no tariff updates | Manifest, DB fixture regression |
| Boundary three minutes after start; midnight guard | Minute-aligned source start, staging boundary 180s, 2-minute day margin | Contract tests and timestamps in report |
| 20/20 invoices match independent spreadsheet | Real OCPP, two independent half-up price segments, workbook formulas from source readings | `reconciliation.xlsx`, JSON per run |
| Exactly one debit and correct wallet/ledger | Read-only checks of sessions, invoice lines, ledger and balance | Failure/mutation tests, replay on real sockets |
| Three new runs all correct | `verify-suite`, distinct run and station IDs | Three successful **staging** reports, TV6 review |
| Parameterized fast CI | `--mode ci`, count/duration/boundary flags, historical buffered source clock | 20 real sockets on disposable PostgreSQL |
| T-107 manifest integration | `scripts/t107_manifest_run.py:apply_run` and `cleanup_run` | T-88 seed, concurrent/repeated runs, cleanup tests |

T-108 owns station/charger/connector and the initial tariff. The T-107 adapter
owns driver/card/wallet/manual funding. `run_id` is a UUID; retry uses the same
manifest and deterministic OCPP message IDs, while new runs use fresh IDs.
PR #133 đã merge hai module dùng chung. T-108 gọi `prepare_station`, rồi adapter
`scripts.t107_manifest_run.apply_run` nhận manifest để seed; cleanup cũng dùng
adapter T-107. Không duy trì schema/fixture khác với develop.

T-102 đã merge và được kiểm chứng trên staging. Test 20 socket của T-108 phải
đạt với worker thật tự settlement; không tự gọi `tru_vi` hay đặt settlement bằng
fixture khi luồng thực tế thất bại. Oracle/report vẫn từ chối thiếu settlement.

## Installation and environment

```powershell
python -m pip install -e ".[dev,acceptance]"
```

Run from the repository root. Configure `DATABASE_URL` privately for the
verified isolated PostgreSQL test database, with all migrations applied. The
OCPP server must use that **same** database and have T-102 runtime settlement
enabled. An existing active test administrator is required for T-88.
`--ocpp-url` is the server origin (e.g. `wss://<staging-host>`), not `/ocpp/...`.

`T108_ALLOW_TEST_RUN=YES` and `--confirm-test-environment` acknowledge the target;
they are not an automatic production detector. Source revision in the manifest
identifies the runner checkout; independently record the deployed server revision
with the staging evidence. No credentials/passwords are printed or stored in artifacts.

## Run staging

Plan only (no DB connection):

```powershell
python -m scripts.t108_staging plan --output .local/t108
```

For actual runs generate a fresh plan at invocation time. A previously saved
plan can expire before its scheduled start and must not have its tariff edited.

```powershell
$env:T108_ALLOW_TEST_RUN = 'YES'
python -m scripts.t108_staging run --admin-email <test-admin-email> --ocpp-url <staging-ws-origin> --confirm-test-environment
```

Default: 20 chargers; 360s sessions; 2 kWh; 100,000 VND initial wallet funding;
prices 2,000/3,000/2,500 VND/kWh; boundary at start+180s; second boundary after
the session. Rates/funding are illustrative test configuration, not a business
tariff. CLI also exposes `--rates R1 R2 R3`, `--amount-vnd`, `--energy-wh` and
`--sample-seconds`. A saved manifest rejects CLI configuration overrides.
The immutable configuration hash is stored in the fixture station marker:
editing the run inputs after seed is rejected rather than silently reused.

Start is scheduled at a future minute boundary with 2–3 minutes of preparation
time. A staging participant dispatched more than 2 seconds from that schedule
fails the evidence check; this is a dispatch tolerance, not an OCPP latency SLA.
MeterValues are sent every 30s and at the tariff boundary. Stop reason
`EVDisconnected` explicitly proves release; no idle period is generated.

Outputs under `.local/t108/<run_id>/`:
- `manifest.json`: stable identities, configuration, baseline balance, runner revision.
- `trace-001.json` ...: source readings and acknowledged OCPP steps; no secrets.
- `report.json`: per-session discrepancies and overall result.
- `reconciliation.xlsx`: summary, independent formulas and source readings.

Excel recalculates formulas on open. JSON includes independently calculated
numeric answers so a missing spreadsheet formula cache cannot produce a pass.
Money is half-up rounded **per tariff segment**, then summed. No production
calculator is imported into the oracle. T-78's fixed-answer regression remains
the external correctness reference.

Retry without replacing identities or funding:

```powershell
python -m scripts.t108_staging run --manifest .local/t108/<run-id>/manifest.json --admin-email <test-admin-email> --ocpp-url <staging-ws-origin> --confirm-test-environment
```

Completed traces replay StopTransaction twice using the same message ID. Missing
settlement is waited for up to 60s and produces a failed report; the runner never
calls `tru_vi`, overrides settlement or repairs the application under test.
Unexpected financial state/extra sessions fail. One runner/cleanup per run is
serialized by a PostgreSQL session advisory lock, explicitly released on exit.

Repeat a **new run** three times, then verify the three reports:

```powershell
python -m scripts.t108_staging verify-suite --reports <run-a>/report.json <run-b>/report.json <run-c>/report.json
```

The verifier rejects duplicate runs/stations, CI-mode evidence and partial or
failed fleets. Passing is an evidence candidate; TV6 still reviews S-37.

## Fast local/CI and cleanup

```powershell
python -m scripts.t108_staging run --mode ci --count 2 --duration-seconds 120 --boundary-seconds 60 --admin-email <test-admin-email> --ocpp-url ws://127.0.0.1:8000 --confirm-test-environment
python -m scripts.t108_staging cleanup --manifest .local/t108/<run-id>/manifest.json --confirm-test-environment
```

CI mode sends buffered historical timestamps without waiting for wall time;
it always labels its reports CI and never qualifies as staging acceptance.
All synthetic sessions must fit the current station day because T-68 only
allows a new first tariff effective today.

Cleanup archives only the selected run's station/chargers/connectors, deactivates
its identities and blocks its cards. It refuses open/unsettled sessions, retains
wallet/ledger/audit/invoice/session evidence and is repeatable. Other runs are
preserved. Cleanup is logical, as approved in this chat; do not bypass immutable
history triggers. Cleaned runs cannot be re-seeded; use a new run.

## Verification and remaining gate

```powershell
python -m pytest tests/test_t108_acceptance.py tests/test_t108_ocpp.py tests/test_t78_billing_answers.py -q
ruff check .
ruff format --check .
mypy src
```

The OCPP regression uses 20 real sockets and disposable migrated PostgreSQL.
It requires T-102's actual worker to settle all sessions automatically, then
checks positive reporting and replay without another invoice/debit. It does
not prepare settled data manually. Independent verifier tests reject missing
settlement and inconsistent financial evidence.

T-102 (#132), T-103 (#136) and T-107 (#133) are integrated from develop
`7f76f96a`. Local checks passed 49 tests plus Ruff lint/format and mypy (114 src
files). Local or CI success alone does not replace the three fresh staging
runs or TV6's review, and never changes Jira status.
