export const occupationReviewLabels: Record<string, string> = {
  occupation_invalid_release_time: 'Thời điểm rút súng không khớp lịch sử phiên',
  occupation_missing_status_timestamp: 'Thiếu thời điểm trạng thái đầu nối để đối chiếu phí chiếm trụ',
  occupation_status_after_release: 'Đầu nối báo còn chiếm trụ sau khi đã xác nhận rút súng',
  occupation_charging_after_stop: 'Đầu nối báo đang sạc sau khi giao dịch đã kết thúc',
  occupation_interrupted_status: 'Trạng thái đầu nối bị gián đoạn trong khoảng chiếm trụ',
  occupation_offline_gap: 'Mất liên lạc khi đang chờ giải phóng đầu nối',
  occupation_replaced_before_release: 'Có phiên mới nhưng chưa xác nhận rút súng của phiên trước',
  invoice_invalid_occupation_history: 'Lịch sử chiếm trụ chưa đủ nhất quán để lập hóa đơn',
}

export const occupationHistoryLabels: Record<string, string> = {
  occupation_status: 'Ghi nhận trạng thái để đối chiếu phí chiếm trụ',
  connector_released: 'Đã xác nhận rút súng',
}
