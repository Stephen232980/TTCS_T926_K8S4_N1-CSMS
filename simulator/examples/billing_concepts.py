"""Contributor's T-80/T-81/T-104 learning examples, not backend integration.

These functions only print and update process-local dictionaries. They create no
persisted invoice, wallet debit or debt-recovery job and must not be imported by
S-26/OCPP acceptance runners. Production billing remains in src/modules/billing.
"""


# ==========================================
# [T-80] TÍNH TIỀN VÀ LẬP HÓA ĐƠN
# ==========================================
def tinh_tien(start_wh: int, stop_wh: int, don_gia_kwh: float = 3500.0) -> float:
    luong_dien_kwh = (stop_wh - start_wh) / 1000
    return luong_dien_kwh * don_gia_kwh


def lap_hoa_don(start_wh: int, stop_wh: int) -> float:
    print("--- BẮT ĐẦU LẬP HÓA ĐƠN ---")
    print(f"Chỉ số bắt đầu: {start_wh} Wh")
    print(f"Chỉ số kết thúc: {stop_wh} Wh")

    tong_tien = tinh_tien(start_wh, stop_wh)

    print(f"Điện năng tiêu thụ: {(stop_wh - start_wh) / 1000} kWh")
    print(f"Tổng tiền thanh toán: {tong_tien:,.0f} VNĐ")
    print("---------------------------\n")
    return tong_tien


# ==========================================
# [T-81] CHỐT PHIÊN VÀ JOB THU NỢ
# ==========================================
DATABASE_PHIEN_SAC = {}


def chot_phien(
    transaction_id: int, start_wh: int, stop_wh: int, thanh_toan_thanh_cong: bool
) -> None:
    print(f"\n⚡ BẮT ĐẦU CHỐT PHIÊN CHO TRANSACTION: {transaction_id}")
    tong_tien = lap_hoa_don(start_wh, stop_wh)
    trang_thai = "DA_THANH_TOAN" if thanh_toan_thanh_cong else "CHO_THANH_TOAN"

    DATABASE_PHIEN_SAC[transaction_id] = {
        "transaction_id": transaction_id,
        "tong_tien": tong_tien,
        "trang_thai": trang_thai,
    }
    print(f"=> Trạng thái phiên {transaction_id} được lưu vào hệ thống: {trang_thai}")


def job_nhat_phien_chua_thanh_toan() -> None:
    print("\n" + "=" * 50)
    print("🔍 [BACKGROUND JOB] QUÉT PHIÊN CHƯA HOÀN TẤT THANH TOÁN...")
    danh_sach_no = [
        phien
        for phien in DATABASE_PHIEN_SAC.values()
        if phien["trang_thai"] == "CHO_THANH_TOAN"
    ]

    if not danh_sach_no:
        print("✅ Không có khách hàng nào nợ tiền. Hệ thống sạch sẽ!")
        print("=" * 50 + "\n")
        return

    for phien in danh_sach_no:
        tx_id = phien["transaction_id"]
        tien_no = phien["tong_tien"]
        print(f"⚠️ Phát hiện Transaction {tx_id} đang nợ {tien_no:,.0f} VNĐ!")
        print(f"   -> Đang gửi yêu cầu trừ tiền lại cho Transaction {tx_id}...")
        DATABASE_PHIEN_SAC[tx_id]["trang_thai"] = "DA_THANH_TOAN"
        print("   -> ✅ Thu hồi nợ thành công! Đã cập nhật trạng thái DA_THANH_TOAN.")
    print("=" * 50 + "\n")


# ==========================================
# [T-104] NGƯỠNG TỐI THIỂU & KIỂM TRA SỐ DƯ
# ==========================================
DATABASE_VI_TIEN = {"SIMTAG-1": 50000.0, "SIMTAG-2": 15000.0, "SIMTAG-3": 100000.0}

CAU_HINH_TRAM = {
    1: 30000.0,
}


def du_so_du_de_sac(id_tag: str, connector_id: int) -> bool:
    print(f"\n💳 [T-104] KIỂM TRA SỐ DƯ THẺ: {id_tag} (CỔNG: {connector_id})")
    so_du = DATABASE_VI_TIEN.get(id_tag, 20000.0)
    nguong_toi_thieu = CAU_HINH_TRAM.get(connector_id, 30000.0)

    print(f"   -> Số dư ví hiện tại: {so_du:,.0f} VNĐ")
    print(f"   -> Ngưỡng trạm yêu cầu: {nguong_toi_thieu:,.0f} VNĐ")

    if so_du >= nguong_toi_thieu:
        print("   -> ✅ HỢP LỆ: Số dư đảm bảo. Cho phép bắt đầu sạc!")
        return True
    else:
        print("   -> ❌ TỪ CHỐI: Số dư quá thấp. Yêu cầu nạp thêm tiền!")
        return False
