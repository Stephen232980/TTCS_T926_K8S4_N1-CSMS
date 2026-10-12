# Staging database runtime and public OCPP

## Separate credentials

The runtime application's `DATABASE_URL` must use a LOGIN/NOSUPERUSER role,
without CREATEDB, CREATEROLE, BYPASSRLS, table ownership or role memberships.
Staging uses `csms_runtime`; retain the existing migration owner separately.
Do not include privileged migration credentials in either backend environment.

The deployment user's private `.env` is the runtime environment; `.env.migrations`
contains the migration owner's DATABASE_URL and is readable only on the host by
that user. Set `MIGRATION_ENV_FILE` to override the default `${ENV_FILE}.migrations`.
Keep both files mode 600. Never commit credentials or print their contents.

The deployment script runs migrations in a separate short-lived container, then
applies `scripts/grant_runtime_permissions.py` as the migration owner before
continuing the normal candidate readiness/rollback sequence. An older image can
use a read-only host copy of the grant script; new images include it normally.
For maintenance of an already-downloaded pinned image, `SKIP_IMAGE_PULL=1`
requires that exact image to exist locally. CI continues to pull by default.

The grant helper provides CRUD for mutable runtime data, sequence usage, and
only SELECT/INSERT for every table protected by an `immutable_*` trigger.
It removes access to Alembic's migration state table and verifies effective
invoice permissions after grants. It refuses privileged/owner/member runtime
roles; inherited or PUBLIC invoice rights cannot silently produce a pass.
Re-run this policy after migrations to protect newly introduced immutable tables.

## Public OCPP route

The staging Caddyfile must include the following before the frontend fallback:

```caddyfile
handle /ocpp/* {
    reverse_proxy csms-app:8000
}
```

Keep `/api/*` routed to the backend and the remaining paths routed to the frontend.
Validate the Caddyfile before reload. Do not replace OCPP with an HTTP-only
frontend fallback or use an SSH tunnel as public-ingress acceptance evidence.

## Verified staging correction, 12 October 2026

The live backend remains at image `c8c8b601`, with its application DB role changed
to `csms_runtime`; schema/data and frontend image were not replaced.
The owner role `csms` is retained for migration/rollback, outside runtime config.
Candidate and main `/health/ready` checks passed. Seven immutable tables are
restricted. UPDATE/DELETE on invoices and invoice_lines now fail with SQLSTATE
42501 using the actual running backend connection.

Public `wss://csms-staging.daominhtam2k6.id.vn/ocpp/<code>` now accepts real
OCPP 1.6J. Sessions #4/#5 were created over the public endpoint and the worker
created the expected 5,000 VND energy/idle invoices. Prior invoice snapshots
and needs-review amount masking remained correct. Real UI at 360px has no
horizontal overflow or page errors. Alembic's owner connection sees revision
`d180018a2026`; credentials were not exposed.

Backups are retained on the server in the restricted directory
`/home/azureadmin/csms-config-backups/20261012T032140Z`, together with the stopped
previous backend `csms-app-permissions-backup-20261012T032140Z`. Restore the previous
container/environment/Caddyfile if verification fails; do not delete financial data.

The server's `/tmp/deploy_staging.sh` receives this correction for manual runs.
The repository patch must be reviewed and merged before a future GitHub Actions
deployment: Actions uploads its repository script and can overwrite that copy.
An old script using the now-restricted runtime role cannot perform DDL; candidate
deployment should fail rather than restoring application superuser access.
