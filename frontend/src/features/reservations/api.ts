import { notifySessionUnauthorized } from '../auth/sessionEvents'

export type ReservationStatus = 'pending' | 'uncertain' | 'active' | 'cancel_pending' | 'expiry_release_pending' | 'consumed' | 'cancelled' | 'rejected' | 'expired'
export interface Reservation {
  id: string; station_id: string; station_name: string; connector_id: string
  charge_point_code: string; connector_number: number; status: ReservationStatus
  created_at: string; arrival_at: string; expires_at: string; updated_at: string
  can_cancel: boolean; no_show_exempt: boolean; outcome: string | null; session_id: number | null
  no_show_fee_vnd?: string; fee_decision?: string; fee_reason?: string; fee_ledger_id?: number | null
}
export interface ReservationPage { items: Reservation[]; page: number; total_pages: number; total: number; generated_at: string }
export interface BookingBody { request_id: string; connector_id: string; arrival_at: string | null; accepted_fee_vnd?: number; accepted_policy_version?: number }
export const labels: Record<ReservationStatus, string> = {
  pending: 'Đang gửi yêu cầu đến trụ', active: 'Đã xác nhận giữ chỗ', uncertain: 'Chưa xác minh được giữ chỗ',
  cancel_pending: 'Đang chờ xác nhận hủy', expiry_release_pending: 'Đã quá hạn, đang xác minh giải phóng',
  consumed: 'Đã dùng để sạc', cancelled: 'Đã hủy', rejected: 'Trụ không giữ chỗ', expired: 'Đã hết hạn',
}
const messages: Record<string, string> = {
  connector_reserved: 'Đầu nối đã có người giữ chỗ. Chọn đầu nối khác.',
  connector_unavailable: 'Đầu nối không còn rảnh. Tải lại trạng thái để chọn đầu nối khác.',
  driver_already_reserved: 'Bạn đã có một đặt chỗ đang giữ đầu nối. Kiểm tra Đặt chỗ của bạn trước khi đặt tiếp.',
  reservation_capability_unverified: 'Chưa xác minh trụ hỗ trợ đặt chỗ. Bấm kiểm tra hỗ trợ rồi thử lại.',
  reservation_unsupported: 'Trụ không hỗ trợ đặt chỗ. Chọn trụ khác.',
  station_or_charger_unavailable: 'Trạm hoặc trụ đang không khả dụng. Tải lại để kiểm tra.',
  reservation_arrival_out_of_range: 'Giờ đến phải từ bây giờ đến hai giờ tới.',
  reservation_request_conflict: 'Mã yêu cầu đã được dùng cho thao tác khác. Tải lại đặt chỗ của bạn.',
  reservation_policy_changed: 'Phí không đến đã thay đổi. Kiểm tra và xác nhận mức phí mới trước khi đặt.',
  reservation_expired: 'Đặt chỗ đã quá hạn. Không thể hủy ngược thời gian.',
  reservation_consumed: 'Đặt chỗ đã được dùng để sạc nên không thể hủy.',
  reservation_not_cancellable: 'Đặt chỗ chưa thể hủy ở trạng thái hiện tại. Tải lại để kiểm tra.',
  reservation_identity_unavailable: 'Định danh sạc chưa hợp lệ. Liên hệ hỗ trợ trước khi đặt chỗ.',
  wallet_low: 'Ví chưa đủ số dư để đặt chỗ. Nạp thêm tiền rồi thử lại.',
  wallet_missing: 'Chưa tìm thấy ví. Kiểm tra ví trước khi đặt chỗ.',
  wallet_locked: 'Ví đang bị khóa. Liên hệ hỗ trợ trước khi đặt chỗ.',
  tariff_unavailable: 'Trạm chưa có biểu giá hợp lệ để đặt chỗ.',
  power_unavailable: 'Công suất trạm chưa sẵn sàng. Chọn trạm khác hoặc thử lại sau.',
}
export class ReservationApiError extends Error {
  readonly status: number
  constructor(status: number, detail: unknown) {
    const code = typeof detail === 'string' ? detail : detail && typeof detail === 'object' && 'reason' in detail ? String(detail.reason) : ''
    super(messages[code] ?? (status === 401 ? 'Phiên đăng nhập đã hết hạn.' : status === 403 ? 'Bạn không có quyền thực hiện thao tác này.' : 'Không đọc hoặc lưu được đặt chỗ. Tải lại để kiểm tra.'))
    this.status = status
  }
}
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
export function definitiveRejection(cause: unknown): cause is ReservationApiError {
  return cause instanceof ReservationApiError && cause.status >= 400 && cause.status < 500 && cause.status !== 408
}
export async function reservationRequest<T>(path = '', options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}/api/v1/driver/reservations${path}`, { credentials: 'include', ...options })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) { const data = await response.json().catch(() => ({})) as { detail?: unknown }; throw new ReservationApiError(response.status, data.detail) }
  return await response.json() as T
}
export const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export function changed() { window.dispatchEvent(new Event('csms:reservation-changed')) }
export function dateLabel(value: string) { return new Date(value).toLocaleString('vi-VN') }
