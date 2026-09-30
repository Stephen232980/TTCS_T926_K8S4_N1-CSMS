#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${1:-${IMAGE_NAME:-}}"
if [ -z "${IMAGE_NAME}" ]; then
  echo "[ERROR] Missing frontend Docker image. Usage: $0 <image_name>"
  exit 1
fi

APP_CONTAINER="${FRONTEND_CONTAINER:-csms-frontend}"
CANDIDATE_CONTAINER="${FRONTEND_CANDIDATE_CONTAINER:-csms-frontend-candidate}"
BACKUP_CONTAINER="${APP_CONTAINER}-backup"
APP_PORT="${FRONTEND_PORT:-80}"
CANDIDATE_PORT="${FRONTEND_CANDIDATE_PORT:-8081}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-csms-app}"
NETWORK_NAME="${NETWORK_NAME:-}"

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -Fxq "$1"
}

check_frontend() {
  local port="$1"
  local root_status
  local api_status

  root_status=$(curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port}/" || echo "000")
  api_status=$(curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port}/api/v1/auth/me" || echo "000")

  [ "${root_status}" = "200" ] && [ "${api_status}" = "401" ]
}

if [ -n "${GHCR_TOKEN:-}" ]; then
  if [ -z "${GHCR_USER:-}" ]; then
    echo "[ERROR] GHCR_USER is required when GHCR_TOKEN is set."
    exit 1
  fi

  echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin
fi

docker pull "${IMAGE_NAME}"

if [ -z "${NETWORK_NAME}" ]; then
  NETWORK_NAME=$(docker inspect \
    --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' \
    "${BACKEND_CONTAINER}" 2>/dev/null | head -n 1)
fi

if [ -z "${NETWORK_NAME}" ] || ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  echo "[ERROR] Cannot find the Docker network used by '${BACKEND_CONTAINER}'."
  exit 1
fi

if container_exists "${CANDIDATE_CONTAINER}"; then
  docker rm -f "${CANDIDATE_CONTAINER}"
fi

if container_exists "${BACKUP_CONTAINER}"; then
  echo "[ERROR] Backup container '${BACKUP_CONTAINER}' already exists; refusing to overwrite it."
  exit 1
fi

docker run -d \
  --name "${CANDIDATE_CONTAINER}" \
  --network "${NETWORK_NAME}" \
  -p "127.0.0.1:${CANDIDATE_PORT}:80" \
  "${IMAGE_NAME}"

CANDIDATE_HEALTHY=0
for _ in $(seq 1 15); do
  if check_frontend "${CANDIDATE_PORT}"; then
    CANDIDATE_HEALTHY=1
    break
  fi
  sleep 2
done

if [ "${CANDIDATE_HEALTHY}" -ne 1 ]; then
  echo "[ERROR] Frontend candidate failed its root or API proxy health check."
  docker logs --tail 50 "${CANDIDATE_CONTAINER}" || true
  docker rm -f "${CANDIDATE_CONTAINER}" || true
  exit 1
fi

HAS_OLD_APP=0
if container_exists "${APP_CONTAINER}"; then
  HAS_OLD_APP=1
  docker stop "${APP_CONTAINER}"
  if ! docker rename "${APP_CONTAINER}" "${BACKUP_CONTAINER}"; then
    docker start "${APP_CONTAINER}" || true
    docker rm -f "${CANDIDATE_CONTAINER}" || true
    exit 1
  fi
fi

docker rm -f "${CANDIDATE_CONTAINER}"

START_MAIN_SUCCESS=1
docker run -d \
  --name "${APP_CONTAINER}" \
  --network "${NETWORK_NAME}" \
  -p "${APP_PORT}:80" \
  --restart unless-stopped \
  "${IMAGE_NAME}" || START_MAIN_SUCCESS=0

MAIN_HEALTHY=0
if [ "${START_MAIN_SUCCESS}" -eq 1 ]; then
  for _ in $(seq 1 15); do
    if check_frontend "${APP_PORT}"; then
      MAIN_HEALTHY=1
      break
    fi
    sleep 2
  done
fi

if [ "${MAIN_HEALTHY}" -ne 1 ]; then
  echo "[ERROR] Frontend failed on the main port; restoring the previous container."
  docker logs --tail 50 "${APP_CONTAINER}" 2>/dev/null || true
  docker rm -f "${APP_CONTAINER}" 2>/dev/null || true

  if [ "${HAS_OLD_APP}" -eq 1 ]; then
    docker rename "${BACKUP_CONTAINER}" "${APP_CONTAINER}"
    docker start "${APP_CONTAINER}"
  fi
  exit 1
fi

docker rm -f "${BACKUP_CONTAINER}" 2>/dev/null || true
echo "[SUCCESS] Frontend deployed on port ${APP_PORT}."
