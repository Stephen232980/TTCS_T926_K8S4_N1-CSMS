export function needsSessionWarning(reasons: string[], ended: boolean): boolean {
  return reasons.some(reason => reason !== 'manual_closure' &&
    !(reason === 'occupation_missing_status_timestamp' && !ended))
}

export function durationText(minutes: number): string {
  const value = Math.max(0, Math.floor(minutes))
  const days = Math.floor(value / 1440), hours = Math.floor((value % 1440) / 60), rest = value % 60
  return [days ? `${days} ngày` : '', hours ? `${hours} giờ` : '', rest || (!days && !hours) ? `${rest} phút` : ''].filter(Boolean).join(' ')
}

export function reviewGuidance(reason: string): string {
  if (reason === 'occupation_missing_status_timestamp')
    return 'Trụ đã gửi trạng thái thiếu thời gian. Đây là ghi chú chất lượng dữ liệu, không tự nó chứng minh sạc bị lỗi. Khi phiên kết thúc, cần đối chiếu lịch sử trạng thái trước khi tính phí chiếm trụ.'
  if (reason.includes('meter') || reason === 'negative_start_meter')
    return 'Đối chiếu công tơ đầu, cuối và các số đo theo thời gian. Nếu số đo giảm hoặc mâu thuẫn, kiểm tra trụ và chuyển bộ phận kỹ thuật; không tự sửa số đo để chốt tiền.'
  if (reason === 'offline_timeout' || reason === 'remote_stop_not_confirmed')
    return 'Kiểm tra kết nối và tình trạng sạc thực tế. Khi trụ kết nối lại, đối chiếu tin kết thúc và lịch sử phục hồi. Đóng hồ sơ chỉ dùng sau khi đã kiểm tra trụ; thao tác này không dừng sạc.'
  if (reason.startsWith('occupation_'))
    return 'Đối chiếu thời điểm dừng sạc, trạng thái đầu nối và thời điểm rút súng. Nếu thiếu dữ liệu, chuyển bộ phận vận hành kiểm tra trước khi xác nhận phí chiếm trụ.'
  if (reason.startsWith('authorization_') || reason === 'reservation_not_verified')
    return 'Kiểm tra thẻ, tài khoản và thông tin đặt chỗ tại thời điểm bắt đầu. Đối chiếu nhật ký trước khi yêu cầu tài xế thử lại.'
  if (reason === 'available_with_open_session' || reason === 'replaced_open_session')
    return 'Kiểm tra phiên thực tế tại đầu nối và lịch sử phục hồi. Xác định phiên nào còn sạc trước khi gửi lệnh hoặc đóng hồ sơ.'
  if (reason === 'stop_before_start') return 'Đối chiếu giờ của trụ và thứ tự thông điệp bắt đầu/kết thúc; chuyển kỹ thuật kiểm tra nếu thời gian không khớp.'
  if (reason === 'manual_closure') return 'Xem người thực hiện, lý do đóng hồ sơ và số đo dùng để chốt trong lịch sử phục hồi.'
  return 'Đối chiếu trạng thái trụ, số đo và lịch sử phục hồi; chuyển bộ phận phụ trách kèm mã phiên nếu chưa xác định được nguyên nhân.'
}
