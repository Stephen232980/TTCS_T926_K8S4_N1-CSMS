# S-62 encrypted PostgreSQL backup and recovery

## Scope and defaults

This deployment uses only the existing staging machine, as requested by the
operator on 2026-10-19. Encrypted archives live in `/var/lib/csms-backup`, outside
the database volume and backend container. Default schedule: **02:00
Asia/Ho_Chi_Minh**. Default retention: **3 successful archives**, not 14 days;
manual backups count toward that limit. Keep the key separately in
`/etc/csms-backup/s62.key` with restricted access.

Off-host mirroring is optional and disabled by default (`S62_REMOTE_MOUNT=`).
No additional server or cloud account is required. Local backups support logical
recovery, but loss of the host/disk can also lose the archives and key. This
limitation does not replace the original S-62 acceptance: nightly encrypted
backups and at least one successful restore into an empty environment.

## Runtime installation (Linux/systemd)

1. Review/build a fixed image from this revision:

   ```sh
   docker build -f ops/backup/Dockerfile -t csms-s62-backup:local .
   ```

2. Check free disk space and use `/var/lib/csms-backup` for persistent local
   archives. Do not place backups inside the database volume or container writable
   layer. Leave `S62_REMOTE_MOUNT` empty. If off-host storage becomes available,
   mount it persistently and configure this optional field; the runner will then
   require a real mount and verify the encrypted mirror before retention.

3. Prepare configuration (run as the server administrator):

   ```sh
   install -d -m 0700 /etc/csms-backup /var/lib/csms-backup
   install -m 0600 ops/backup/runner.conf.example /etc/csms-backup/runner.conf
   install -m 0600 ops/backup/database.env.example /etc/csms-backup/database.env
   ```

   Fill in the actual Docker database network, image tag, optional mirror (empty for staging-only),
   credentials, and approved retention. Obtain the network from deployment
   configuration or `docker inspect csms-db`; do not guess it.
   Do not commit the filled files. URL-encode credentials in DATABASE_URL.
   Supported URL options: sslmode, sslrootcert, sslcert, sslkey, connect_timeout.
   When using TLS files, add explicit read-only mounts for them to the runner.
   Unknown URL options fail rather than silently weakening the connection.

4. Provision a **dedicated backup login**, separate from `csms_runtime`, with
   CONNECT to the source database, `pg_read_all_data`, and BYPASSRLS if the source
   uses RLS. Check schema privileges and a real pg_dump under that role, including
   `privacy_private`; do not grant additional rights to the application runtime.
   Keep this high-trust read credential in the root-readable env file.
   Role provisioning/password management belongs to the server administrator.

5. Generate the encryption key directly into a restricted file, without logging it:

   ```sh
   (umask 077; docker run --rm --entrypoint python3 csms-s62-backup:local \
     -c 'from cryptography.fernet import Fernet; import sys; sys.stdout.buffer.write(Fernet.generate_key())' \
     > /etc/csms-backup/s62.key)
   ```

   Keep the key outside the backup directory. If possible, retain a password-manager
   copy on an existing device; this does not require another server. Record the key version and which archives it protects. Preserve
   old keys for all retained archives during rotation; never overwrite the sole
   recoverable key. The job supports S62_BACKUP_KEY_FILE (preferred) and legacy
   S62_BACKUP_KEY; it does not print either value.

6. Install and run the **same entrypoint** used by the timer:

   ```sh
   install -d /usr/local/libexec
   install -m 0750 ops/backup/run-backup.sh /usr/local/libexec/csms-run-backup
   install -m 0644 ops/backup/csms-backup*.service ops/backup/csms-backup.timer /etc/systemd/system/
   systemctl daemon-reload
   systemctl start csms-backup.service
   journalctl -u csms-backup.service --since today
   ```

   Confirm a nonempty encrypted archive in the local store. When the optional mirror
   is enabled, confirm both stores and matching SHA-256.
   Only then enable the timer:

   ```sh
   systemctl enable --now csms-backup.timer
   systemctl list-timers csms-backup.timer
   ```

The timer catches up one missed run after downtime. systemd prevents concurrent
runs of this unit; a directory lock also rejects a second writer using the same
local store. PostgreSQL commands time out after 1800 seconds; the service stops
its dedicated container after 3600 seconds. Failures leave the unit failed and
emit a `daemon.err` syslog record via csms-backup-failure.service. Connect that
record/failed-unit condition to the site's monitoring for remote notification;
this PR does not configure an email or external alert account. Test it with an
invalid disposable connection before relying on the schedule.

## Restore drill / disaster recovery

Use a **new empty database** on an isolated PostgreSQL 16 instance. Restore requires
S62_RESTORE_DATABASE_URL and rejects nonempty targets, including custom schemas,
public relations, routines and types. It never uses `--clean` or drops a database.
The instance must be isolated from the active application/workers; the empty check
is a guard, not a concurrency lock against another administrator writing to it.

Use an encrypted archive from `/var/lib/csms-backup` and the matching key from
`/etc/csms-backup/s62.key` (or its saved copy). Provision the original owner/ACL roles on the recovery instance through
the approved infrastructure/bootstrap process before restore. A database dump is
not a backup of cluster-wide roles/passwords; this script preserves original
ownership/ACLs and intentionally does not use `--no-owner`/`--no-acl`. Source and
recovery roles may differ only if an explicitly reviewed migration accounts for it.

Create a root-readable recovery env file containing the target connection, then:

```sh
docker run --rm --network RECOVERY_NETWORK --read-only --cap-drop ALL \
  --tmpfs /tmp:rw,noexec,nosuid,size=1g,mode=1777 \
  --env-file /etc/csms-backup/recovery.env \
  --mount type=bind,src=/secure/recovered-key,dst=/run/secrets/s62.key,readonly \
  --mount type=bind,src=/recovery/encrypted,dst=/archives,readonly \
  csms-s62-backup:local restore /archives/CHOSEN.dump.enc
```

The archive is fully authenticated before pg_restore; restore uses an explicit
`--dbname`, `--exit-on-error` and one transaction. Wrong key, incomplete/modified
archive, connection failure and PostgreSQL errors return nonzero. Logs omit
libpq stderr because it can contain sensitive SQL/connection information.
Successful restore is logged only after PostgreSQL commits. Acceptance remains a
separate step: compare migration revision, all table counts/data, invoice totals,
wallet balances/ledger, foreign keys and sequence positions, then read through the
application on the recovered DB. Replay privacy tombstones newer than the backup
and validate S-57 privacy/runtime grants before opening the recovered service.
Never connect a recovered copy to live payment/OCPP/email workers during a drill.

## Format, files and failure handling

- v2 binds each encrypted chunk to a random file identity and sequence index.
  Authenticated EOF carries count, byte length and SHA-256 of plaintext. Truncation,
  reordering, duplication, cross-file splicing, trailing bytes and wrong keys fail.
- v1 archives are rejected because they cannot prove complete-file integrity.
  Create fresh v2 archives before enabling this job. Retain any old artifacts for
  administrator-led recovery; they are never automatically trusted as v2.
- Plain dumps are created in private temporary directories, cleaned on normal
  exit/failure. The runtime puts them on a size-limited tmpfs, not the persistent
  backup store. Increase the 1 GiB limit only after measuring dump size/capacity.
- Files are atomically published with mode 0600; no partial plaintext is published
  after failed authentication. Do not reuse the source path as decrypt output.
- Mirrored bytes are checksummed before publication. Retention runs only after a
  successful mirror for configured mirrored jobs. A failed copy leaves previous
  backups intact and the job failed; an unmirrored local archive may remain for
  diagnosis and is not proof of off-host completion.
- After SIGKILL/host loss, inspect systemd and the dedicated container before
  removing a stale `/var/lib/csms-backup/.s62.lock` with `rmdir`. Do not automatically
  remove locks while a writer may still exist. Ciphertext `.tmp` files may remain
  after a hard kill; remove only identified stale files after stopping the job.
- Operators should periodically validate recovery from the configured store using
  the matching separately stored key. A checksum alone does not prove recoverability.

## Reproducible local/CI acceptance

Run only on disposable infrastructure; the opt-in test commits fixture data.
Use Python 3.12 with `pip install -e '.[dev]'` and Docker:

```sh
docker network create csms-s62-review
docker run -d --name csms-s62-review-db --network csms-s62-review \
  -p 127.0.0.1:55478:5432 -e POSTGRES_HOST_AUTH_METHOD=trust \
  -e POSTGRES_DB=s62_source postgres:16
# Wait for pg_isready before the next commands.
docker exec csms-s62-review-db createdb -U postgres s62_restore
export DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55478/s62_source
export LEGACY_SETTLEMENT_CUTOFF=1970-01-01T00:00:00+00:00
alembic upgrade head
docker build -f ops/backup/Dockerfile -t csms-s62-backup:review .
export S62_ACCEPTANCE_CONTAINER=csms-s62-review-db
export S62_ACCEPTANCE_TARGET_URL=postgresql+psycopg://postgres@127.0.0.1:55478/s62_restore
pytest tests/test_database_backup.py tests/test_s62_backup_postgres.py -q -s
docker rm -f csms-s62-review-db
docker network rm csms-s62-review
```

Create a fresh empty restore DB for each run. The test compares all public/private
schema table rows and sequences, with real linked session/invoice/wallet/ledger
fixtures, and calls the application session-read service on restored data. It
checks mirror equality and verifies a retry into the populated target is refused.
The mirror in this test is a second local directory: it proves the mirror code,
not actual off-host storage or a deployed scheduler. The dedicated CI workflow
runs this same acceptance on PostgreSQL 16.

## Acceptance status

Local evidence dated 2026-10-19: migrated PostgreSQL 16 source, encrypted backup,
restore into an empty database, comparison of 56 tables and sequences, application
session read and populated-target rejection passed. Additional failure tests cover
archive damage, wrong key, settings validation, locking and failed mirror retention.

Staging evidence dated 2026-10-19 (Asia/Ho_Chi_Minh):

- Installed a separate backup image `csms-s62-backup:8e298bd`, with a dedicated
  `csms_backup` login granted read-only data access; application runtime rights
  were not expanded.
- Executed the installed `csms-backup.service` successfully and enabled
  `csms-backup.timer`. Next scheduled run: **2026-10-20 02:00 Vietnam time**.
- Tested retention through repeated successful runs: exactly **3 encrypted
  archives**, mode 0600, approximately **151.3 MB total** at acceptance time.
- Restored a staging archive (50,424,060 encrypted bytes) to a fresh, isolated
  PostgreSQL 16 container. Restore and checks completed in about 30 seconds.
- Recovered schema revision `m170029a2026`, 56 tables, 192 charging sessions,
  98,547 meter samples, 118 wallets and 6 sequences. All 192 invoice rows,
  252 invoice-line rows and 305 wallet-ledger rows sampled from the live database
  matched the recovered historical records. No foreign key remained unvalidated.
  Live telemetry keeps changing, so this is not a claim that every live table
  matched a single coordinated source snapshot.
- Confirmed the failure-notification unit emits a local syslog message. No remote
  email/notification channel is configured for backup failures.
- Removed the temporary recovery container/network/data after the drill. Active
  backend/database/simulator container identities and start times were unchanged;
  backend readiness remained `ready`.

This establishes deployed backup scheduling and one real restore drill for the
agreed staging-only S-62 scope. The first unattended overnight run has not occurred
at the time of this evidence. Review/merge and Jira status are separate from this
operational evidence. Local-only storage retains the documented host-loss limit.
