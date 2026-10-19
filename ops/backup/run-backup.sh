#!/bin/sh
set -eu
. /etc/csms-backup/runner.conf
test -r /etc/csms-backup/s62.key
# The staging-only deployment leaves S62_REMOTE_MOUNT empty.
set --
if [ -n "${S62_REMOTE_MOUNT:-}" ]; then
  mountpoint -q "$S62_REMOTE_MOUNT" || { echo 'S-62 remote store is not mounted' >&2; exit 1; }
  set -- -e S62_MIRROR_DIR=/mirror --mount "type=bind,src=$S62_REMOTE_MOUNT,dst=/mirror"
fi
exec /usr/bin/docker run --rm --name csms-s62-backup --network "$S62_DOCKER_NETWORK" \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=1g,mode=1777 \
  --env-file /etc/csms-backup/database.env \
  -e S62_KEEP_COUNT="$S62_KEEP_COUNT" \
  --mount type=bind,src=/etc/csms-backup/s62.key,dst=/run/secrets/s62.key,readonly \
  --mount type=bind,src="$S62_LOCAL_DIR",dst=/backups \
  "$@" "$S62_BACKUP_IMAGE" backup
