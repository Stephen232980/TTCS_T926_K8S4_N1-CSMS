#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Script Triển Khai Staging (Candidate Container Pattern & Zero-Downtime Rollback)
# Task: T-03 — Triển khai tự động lên staging bằng Docker
# ==============================================================================

IMAGE_NAME="${1:-${IMAGE_NAME:-}}"
if [ -z "${IMAGE_NAME}" ]; then
  echo "[ERROR] Thiếu tên Docker image. Cách dùng: $0 <image_name>"
  exit 1
fi

APP_CONTAINER="${APP_CONTAINER:-csms-app}"
CANDIDATE_CONTAINER="${CANDIDATE_CONTAINER:-csms-app-candidate}"
BACKUP_CONTAINER="${APP_CONTAINER}-backup"
APP_PORT="${APP_PORT:-8001}"
CANDIDATE_PORT="${CANDIDATE_PORT:-8002}"
NETWORK_NAME="${NETWORK_NAME:-ttcs_t926_k8s4_n1-csms-main_default}"
ENV_FILE="${ENV_FILE:-.env}"

echo "=========================================================="
echo "BẮT ĐẦU TRIỂN KHAI LÊN STAGING"
echo "Image mới: ${IMAGE_NAME}"
echo "Container hiện tại: ${APP_CONTAINER}"
echo "Container thử nghiệm (Candidate): ${CANDIDATE_CONTAINER}"
echo "Container dự phòng (Backup): ${BACKUP_CONTAINER}"
echo "=========================================================="

# 0. Tự động đăng nhập GHCR nếu được cung cấp token
if [ -n "${GHCR_TOKEN:-}" ]; then
  echo "[0/6] Đăng nhập GitHub Container Registry (GHCR)..."
  echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER:-$USER}" --password-stdin || true
fi

# 1. Kéo image mới
echo "[1/6] Kéo Docker image mới..."
docker pull "${IMAGE_NAME}"

# Dọn dẹp container candidate và backup cũ nếu còn sót từ lần chạy trước
docker rm -f "${CANDIDATE_CONTAINER}" "${BACKUP_CONTAINER}" 2>/dev/null || true

# Đảm bảo network docker tồn tại
docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1 || docker network create "${NETWORK_NAME}" || true

# 2. Khởi chạy container candidate trên cổng thử nghiệm
echo "[2/6] Khởi động container candidate trên cổng ${CANDIDATE_PORT}..."
ENV_PARAM=""
if [ -f "${ENV_FILE}" ]; then
  ENV_PARAM="--env-file ${ENV_FILE}"
fi

docker run -d \
  --name "${CANDIDATE_CONTAINER}" \
  --network "${NETWORK_NAME}" \
  ${ENV_PARAM} \
  -p "${CANDIDATE_PORT}:8000" \
  "${IMAGE_NAME}"

# 3. Chạy migration trên candidate
echo "[3/6] Thực thi database migration..."
if ! docker exec "${CANDIDATE_CONTAINER}" alembic upgrade head; then
  echo "[ERROR] Migration thất bại! Dừng và xóa candidate, container cũ (${APP_CONTAINER}) vẫn chạy nguyên vẹn."
  docker rm -f "${CANDIDATE_CONTAINER}" || true
  exit 1
fi

# 4. Kiểm tra sức khỏe container candidate trên cổng thử nghiệm
echo "[4/6] Kiểm tra sức khỏe container candidate (Cổng ${CANDIDATE_PORT})..."
MAX_RETRIES=15
RETRY_INTERVAL=2
CANDIDATE_HEALTHY=0

for i in $(seq 1 ${MAX_RETRIES}); do
  echo "Kiểm tra candidate lần ${i}/${MAX_RETRIES} tới http://127.0.0.1:${CANDIDATE_PORT}/ ..."
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${CANDIDATE_PORT}/" || echo "000")
  READY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${CANDIDATE_PORT}/health/ready" || echo "000")

  if [ "${HTTP_STATUS}" -eq 200 ] && [ "${READY_STATUS}" -eq 200 ]; then
    echo "[SUCCESS] Candidate sẵn sàng! HTTP status = 200."
    CANDIDATE_HEALTHY=1
    break
  fi

  sleep ${RETRY_INTERVAL}
done

if [ "${CANDIDATE_HEALTHY}" -ne 1 ]; then
  echo "=========================================================="
  echo "[FAIL] Candidate thử nghiệm thất bại (không trả HTTP 200)!"
  echo "Hành động: Xóa candidate. GIỮ NGUYÊN CONTAINER CŨ (${APP_CONTAINER})."
  docker logs --tail 50 "${CANDIDATE_CONTAINER}" || true
  docker rm -f "${CANDIDATE_CONTAINER}" || true
  echo "[ROLLBACK THÀNH CÔNG] Container cũ (${APP_CONTAINER}) được giữ nguyên vẹn."
  echo "=========================================================="
  exit 1
fi

# 5. Chuyển đổi phiên bản mới sang CỔNG CHÍNH với cơ chế Backup & Rollback
echo "[5/6] Giữ container cũ làm Backup và triển khai phiên bản mới lên cổng chính (${APP_PORT})..."

# Dừng và đổi tên container cũ thành backup
HAS_OLD_APP=0
if docker ps -a --format '{{.Names}}' | grep -Eq "^${APP_CONTAINER}\$"; then
  HAS_OLD_APP=1
  echo "Đổi tên container cũ '${APP_CONTAINER}' thành '${BACKUP_CONTAINER}'..."
  docker stop "${APP_CONTAINER}" || true
  docker rename "${APP_CONTAINER}" "${BACKUP_CONTAINER}" || true
fi

# Dừng candidate tạm để giải phóng tài nguyên
docker stop "${CANDIDATE_CONTAINER}" 2>/dev/null || true

# Khởi chạy container mới trên cổng chính
START_MAIN_SUCCESS=1
docker run -d \
  --name "${APP_CONTAINER}" \
  --network "${NETWORK_NAME}" \
  ${ENV_PARAM} \
  -p "${APP_PORT}:8000" \
  --restart unless-stopped \
  "${IMAGE_NAME}" || START_MAIN_SUCCESS=0

# 6. Health check lại phiên bản mới trên CỔNG CHÍNH
MAIN_HEALTHY=0
if [ "${START_MAIN_SUCCESS}" -eq 1 ]; then
  echo "[6/6] Health-check lại trang chủ trên cổng chính (${APP_PORT})..."
  for i in $(seq 1 ${MAX_RETRIES}); do
    echo "Kiểm tra cổng chính lần ${i}/${MAX_RETRIES} tới http://127.0.0.1:${APP_PORT}/ ..."
    MAIN_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${APP_PORT}/" || echo "000")
    MAIN_READY=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${APP_PORT}/health/ready" || echo "000")

    if [ "${MAIN_HTTP}" -eq 200 ] && [ "${MAIN_READY}" -eq 200 ]; then
      echo "[SUCCESS] Cổng chính (${APP_PORT}) hoạt động hoàn hảo! HTTP status = 200."
      MAIN_HEALTHY=1
      break
    fi

    sleep ${RETRY_INTERVAL}
  done
fi

# Xử lý kết quả kiểm tra cổng chính
if [ "${MAIN_HEALTHY}" -ne 1 ]; then
  echo "=========================================================="
  echo "[FAIL] Container mới trên cổng chính thất bại hoặc không trả HTTP 200!"
  echo "Hành động: Tiến hành KHÔI PHỤC (Rollback) container cũ từ backup..."
  docker logs --tail 50 "${APP_CONTAINER}" 2>/dev/null || true
  docker rm -f "${APP_CONTAINER}" 2>/dev/null || true
  docker rm -f "${CANDIDATE_CONTAINER}" 2>/dev/null || true

  if [ "${HAS_OLD_APP}" -eq 1 ]; then
    echo "Khôi phục lại container cũ (${APP_CONTAINER})..."
    docker rename "${BACKUP_CONTAINER}" "${APP_CONTAINER}" || true
    docker start "${APP_CONTAINER}" || true
    echo "[ROLLBACK THÀNH CÔNG] Đã khôi phục và chạy lại phiên bản cũ trên cổng ${APP_PORT}."
  fi
  echo "=========================================================="
  exit 1
fi

# Triển khai thành công: dọn dẹp backup và candidate
docker rm -f "${BACKUP_CONTAINER}" "${CANDIDATE_CONTAINER}" 2>/dev/null || true

echo "=========================================================="
echo "[HOÀN TẤT] Triển khai thành công phiên bản mới lên Staging!"
echo "Truy cập: http://localhost:${APP_PORT}/"
echo "=========================================================="
exit 0
