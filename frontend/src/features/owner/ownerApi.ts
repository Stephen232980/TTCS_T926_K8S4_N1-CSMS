import { notifySessionUnauthorized } from '../auth/sessionEvents'

export interface OwnerSession {
  id: number
  station_name: string
  charge_point_code: string
  connector_number: number
  started_at: string
  ended_at: string | null
  energy_kwh: string | null
  latest_meter_wh: string | null
  latest_meter_at: string | null
  meter_start_wh: string
  tag_tail: string
  review_reasons: string[]
  stop_reason: string | null
}
export interface OwnerCard {
  id: string
  driver_email: string
  tag_tail: string
  status: string
  expires_at: string | null
}
export interface OwnerPending {
  id: string
  charge_point_code: string
  action: string
  reason: string
  transaction_id: number | null
  received_at: string
}
export interface MeterSample {
  timestamp: string
  measurand: string
  value: string
  unit: string
  phase: string
  location: string
}
export interface Connection {
  id: string
  code: string
  online: boolean
  last_seen_at: string | null
  connectors: {
    id: string
    number: number
    status: string
    raw_ocpp_status: string | null
    last_error_code: string | null
    last_error_at?: string | null
  }[]
}
export interface OwnerPage<T> {
  items: T[]
  total: number
  page: number
  total_pages: number
}

export class OwnerApiError extends Error {
  readonly status: number
  readonly detail: unknown
  constructor(status: number, detail: unknown, path = '') {
    super(
      status === 403
        ? 'Bạn không có quyền thực hiện thao tác này.'
        : typeof detail === 'string' && errorMessages[detail]
          ? errorMessages[detail]
          : status === 409
          ? 'Thông tin bị trùng hoặc đã thay đổi. Hãy kiểm tra lại.'
          : status === 413
            ? 'Ảnh vượt quá 20 MB. Hãy chọn ảnh nhỏ hơn.'
            : status === 415 || status === 422
                ? path.endsWith('/photo')
                  ? 'Không đọc được ảnh. Chọn ảnh JPEG, PNG hoặc WebP không quá 20 MB và 16 triệu điểm ảnh.'
                  : path.includes('/cards')
                    ? 'Thông tin thẻ chưa hợp lệ. Kiểm tra mã thẻ, email tài xế và ngày hết hạn.'
                    : 'Dữ liệu chưa hợp lệ. Hãy kiểm tra lại thông tin.'
              : 'Không tải hoặc lưu được dữ liệu. Hãy thử lại.',
    )
    this.status = status
    this.detail = detail
  }
}
const errorMessages: Record<string, string> = {
  invalid_station_photo: 'Không đọc được nội dung ảnh. Hãy chọn lại ảnh JPEG, PNG hoặc WebP hợp lệ.',
  station_photo_dimensions_too_large: 'Ảnh vượt quá 16 triệu điểm ảnh. Hãy giảm kích thước chiều rộng và chiều cao.',
  station_photo_too_large: 'Ảnh vượt quá 20 MB. Hãy chọn ảnh nhỏ hơn.',
  unsupported_station_photo_type: 'Chọn ảnh JPEG, PNG hoặc WebP.',
  'Không tìm thấy tài xế đang hoạt động với email này.': 'Không tìm thấy tài xế đang hoạt động với email này. Tài xế cần có tài khoản trước khi được cấp thẻ.',
  'Thẻ đã được khai báo.': 'Mã thẻ đã được cấp. Hãy dùng mã khác hoặc kiểm tra thẻ hiện có.',
}
export async function ownerRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
  const response = await fetch(`${base}/api/v1${path}`, {
    credentials: 'include',
    ...options,
  })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown
    }
    throw new OwnerApiError(response.status, body.detail, path)
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T)
}
export const jsonBody = (method: string, value: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
})
export const clock = (value?: string | null) =>
  value ? new Date(value).toLocaleString('vi-VN') : 'Chưa có dữ liệu'
export const decimal = (value?: string | number | null) =>
  value === null || value === undefined
    ? '—'
    : Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 3 })
export function groupBy<T>(
  items: T[],
  key: (item: T) => string,
): Map<string, T[]> {
  const groups = new Map<string, T[]>()
  for (const item of items) {
    const name = key(item)
    const group = groups.get(name) ?? []
    group.push(item)
    groups.set(name, group)
  }
  return groups
}

export const statusLabel: Record<string, string> = {
  active: 'Đang hoạt động',
  inactive: 'Chưa hoạt động',
  suspended: 'Tạm ngừng',
  blocked: 'Đã khóa',
  available: 'Sẵn sàng',
  charging: 'Đang sạc',
  faulted: 'Có lỗi',
  preparing: 'Đang chuẩn bị',
  finishing: 'Đang kết thúc',
  reserved: 'Đã đặt trước',
  unavailable: 'Không khả dụng',
  suspendedev: 'Xe tạm dừng',
  suspendedevse: 'Trụ tạm dừng',
  unknown: 'Chưa rõ trạng thái',
}

export const measurementLabels: Record<string, string> = { 'Energy.Active.Import.Register': 'Điện năng tích lũy', 'Power.Active.Import': 'Công suất nạp', 'Power.Offered': 'Công suất cấp', 'Current.Import': 'Dòng điện', Voltage: 'Điện áp', Temperature: 'Nhiệt độ', SoC: 'Mức pin', Frequency: 'Tần số' }
export const reviewLabels: Record<string, string> = { authorization_blocked: 'Thẻ, tài khoản hoặc trạm bị khóa', authorization_invalid: 'Thẻ không hợp lệ', authorization_expired: 'Thẻ hết hạn', replaced_open_session: 'Phiên mới thay phiên chưa kết thúc', stop_meter_below_start: 'Số đo cuối nhỏ hơn số đo đầu', meter_regression: 'Số đo điện năng giảm', conflicting_meter_timestamp: 'Số đo trùng thời điểm nhưng khác giá trị', stop_before_start: 'Kết thúc trước khi bắt đầu', reservation_not_verified: 'Chưa xác minh đặt chỗ', negative_start_meter: 'Số đo bắt đầu không hợp lệ', stop_meter_below_latest: 'Số đo cuối nhỏ hơn số đo gần nhất', remote_stop_not_confirmed: 'Chưa nhận xác nhận kết thúc', offline_timeout: 'Trụ ngoại tuyến quá lâu', available_with_open_session: 'Đầu nối sẵn sàng nhưng phiên chưa đóng', manual_closure: 'Phiên đã được đóng tay' }
export const pendingLabels: Record<string, string> = { no_matching_open_session: 'Không khớp phiên đang mở', unknown_transaction: 'Không tìm thấy phiên', already_closed_transaction: 'Phiên đã kết thúc' }
export const historyLabels: Record<string, string> = { reconnected: 'Trụ nối lại, giữ nguyên phiên', offline_timeout: 'Đánh dấu bất thường do ngoại tuyến', available_with_open_session: 'Đầu nối sẵn sàng nhưng phiên chưa kết thúc', charging_resumed: 'Đầu nối báo đang sạc trở lại', late_stop: 'Nhận tin kết thúc sau gián đoạn', manual_closure: 'Đóng tay bằng số đo đã lưu' }
