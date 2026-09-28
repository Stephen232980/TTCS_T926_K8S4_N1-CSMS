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
APP_PORT="${APP_PORT:-8001}"
CANDIDATE_PORT="${CANDIDATE_PORT:-8002}"
NETWORK_NAME="${NETWORK_NAME:-ttcs_t926_k8s4_n1-csms-main_default}"
ENV_FILE="${ENV_FILE:-.env}"

echo "=========================================================="
echo "BẮT ĐẦU TRIỂN KHAI LÊN STAGING"
echo "Image mới: ${IMAGE_NAME}"
echo "Container hiện tại: ${APP_CONTAINER}"
echo "Container thử nghiệm (Candidate): ${CANDIDATE_CONTAINER}"
echo "=========================================================="

# 1. Kéo image mới
echo "[1/5] Kéo Docker image mới..."
docker pull "${IMAGE_NAME}"

# Dọn dẹp container candidate cũ nếu còn sót lại từ lần chạy trước
docker rm -f "${CANDIDATE_CONTAINER}" 2>/dev/null || true

# Đảm bảo network docker tồn tại nếu chưa có
docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1 || docker network create "${NETWORK_NAME}" || true

# 2. Khởi chạy container candidate bên cạnh container cũ
echo "[2/5] Khởi động container candidate trên cổng ${CANDIDATE_PORT}..."
ENV_PARAM=""
if [ -f "${ENV_FILE}" ]; then
  ENV_PARAM="--env-file ${ENV_FILE}"
fi

# Chạy candidate container
docker run -d \
  --name "${CANDIDATE_CONTAINER}" \
  --network "${NETWORK_NAME}" \
  ${ENV_PARAM} \
  -p "${CANDIDATE_PORT}:8000" \
  "${IMAGE_NAME}"

# 3. Chạy migration trên candidate
echo "[3/5] Thực thi database migration..."
docker exec "${CANDIDATE_CONTAINER}" alembic upgrade head || {
  echo "[ERROR] Migration thất bại! Đang rollback giữ nguyên container cũ..."
  docker rm -f "${CANDIDATE_CONTAINER}" || true
  echo "[ROLLBACK THÀNH CÔNG] Đã xóa candidate, container cũ (${APP_CONTAINER}) vẫn chạy nguyên vẹn."
  exit 1
}

# 4. Kiểm tra sức khỏe (Health Check): Gọi trang chủ '/' và '/health/ready'
echo "[4/5] Kiểm tra sức khỏe container candidate..."
MAX_RETRIES=15
RETRY_INTERVAL=2
HEALTHY=0

for i in $(seq 1 ${MAX_RETRIES}); do
  echo "Kiểm tra lần ${i}/${MAX_RETRIES} tới http://127.0.0.1:${CANDIDATE_PORT}/ ..."
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${CANDIDATE_PORT}/" || echo "000")
  READY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${CANDIDATE_PORT}/health/ready" || echo "000")

  if [ "${HTTP_STATUS}" -eq 200 ] && [ "${READY_STATUS}" -eq 200 ]; then
    echo "[SUCCESS] Trang chủ và database sẵn sàng! HTTP status = 200."
    HEALTHY=1
    break
  fi

  sleep ${RETRY_INTERVAL}
done

# 5. Xử lý kết quả kiểm tra
if [ "${HEALTHY}" -ne 1 ]; then
  echo "=========================================================="
  echo "[FAIL] Kiểm tra sức khoẻ thất bại (không trả 200)!"
  echo "Hành động: Dừng và xoá container candidate. GIỮ NGUYÊN CONTAINER CŨ."
  docker logs --tail 50 "${CANDIDATE_CONTAINER}" || true
  docker rm -f "${CANDIDATE_CONTAINER}" || true
  echo "[ROLLBACK THÀNH CÔNG] Container cũ (${APP_CONTAINER}) được giữ nguyên vẹn, không gián đoạn dịch vụ."
  echo "=========================================================="
  exit 1
fi

echo "[5/5] Sức khỏe đạt chuẩn! Chuyển đổi traffic sang phiên bản mới..."
# Dừng và xóa container cũ
if docker ps -a --format '{{.Names}}' | grep -Eq "^${APP_CONTAINER}\$"; then
  echo "Dừng container cũ (${APP_CONTAINER})..."
  docker stop "${APP_CONTAINER}" || true
  docker rm "${APP_CONTAINER}" || true
fi

# Chạy container mới với tên chính thức trên cổng chính
docker run -d \
  --name "${APP_CONTAINER}" \
  --network "${NETWORK_NAME}" \
  ${ENV_PARAM} \
  -p "${APP_PORT}:8000" \
  --restart unless-stopped \
  "${IMAGE_NAME}"

# Xóa container candidate tạm thời
docker rm -f "${CANDIDATE_CONTAINER}" || true

echo "=========================================================="
echo "[HOÀN TẤT] Triển khai thành công phiên bản mới lên Staging!"
echo "Truy cập: http://localhost:${APP_PORT}/"
echo "=========================================================="
exit 0
