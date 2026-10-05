import { notifySessionUnauthorized } from '../auth/sessionEvents'

export type RoleCode =
  | 'admin'
  | 'operator'
  | 'station_owner'
  | 'driver'
  | 'accountant'
export interface Role {
  code: RoleCode
  name: string
}
export interface Account {
  id: string
  email: string
  roles: RoleCode[]
  status: string
  created_at: string
  updated_at: string
}
export interface Page<T> {
  items: T[]
  page: number
  total: number
  total_pages: number
}
export interface AccountState {
  email: string
  roles: RoleCode[]
  status: string
}
export interface AccountAudit {
  permission?: string | null
  actor_roles?: string[] | null
  id: string
  actor_id: string
  actor_email: string
  target_id: string
  action: string
  created_at: string
  before: AccountState | null
  after: AccountState
}
export interface ControlAudit {
  permission?: string | null
  actor_roles?: string[] | null
  id: string
  actor: string
  charge_point_code: string
  transaction_id: number | null
  action: string
  payload: Record<string, unknown>
  created_at: string
  status: string
  received_at: string | null
}
export interface HealthMetrics {
  online_charge_points: number
  registered_charge_points: number
  running_sessions: number
  error_messages_5m: number | null
  error_messages_observed_5m: number
  response_latency_ms: number | null
  response_count_5m: number
  window_complete: boolean
}
export interface Health {
  generated_at: string
  refresh_after_seconds: number
  stale_after_seconds: number
  status: 'current' | 'stale' | 'no_data'
  snapshot: null | {
    collected_at: string
    window_start: string
    window_end: string
    metrics: HealthMetrics
  }
}
export interface HealthHistory {
  from_at: string
  to_at: string
  available_since: string | null
  resolution_seconds: number
  aggregation: string
  points: {
    bucket_start: string
    measured_at: string | null
    metrics: HealthMetrics | null
  }[]
}
export class AdminApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: { field: string; message: string }[]
  constructor(
    status: number,
    code: string,
    message: string,
    fields: { field: string; message: string }[] = [],
  ) {
    super(message)
    this.status = status
    this.code = code
    this.fields = fields
  }
}
export async function adminRequest<T>(
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
    const body = await response.json().catch(() => ({}))
    const message =
      response.status === 403
        ? 'Bạn không có quyền truy cập chức năng này.'
        : (body.error?.message ??
          (typeof body.detail === 'string'
            ? body.detail
            : 'Không tải hoặc lưu được dữ liệu. Hãy thử lại.'))
    throw new AdminApiError(
      response.status,
      body.error?.code ?? '',
      message,
      body.error?.fields ?? [],
    )
  }
  return response.status === 204
    ? (undefined as T)
    : (response.json() as Promise<T>)
}
export const writeJson = (method: string, value: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
})
export const queryString = (values: Record<string, string | number>) =>
  new URLSearchParams(
    Object.entries(values)
      .filter(([, v]) => v !== '')
      .map(([k, v]) => [k, String(v)]),
  ).toString()
export const dateTime = (value?: string | null) =>
  value
    ? new Date(value).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' })
    : 'Chưa có dữ liệu'
export const numberText = (value: number | null | undefined) =>
  value == null
    ? '—'
    : value.toLocaleString('vi-VN', { maximumFractionDigits: 2 })
export const statusNames: Record<string, string> = {
  active: 'Hoạt động',
  suspended: 'Đã khóa',
  deactivated: 'Ngừng hoạt động',
  pending_deletion: 'Chờ xóa',
  anonymized: 'Đã ẩn danh',
}
export const roleNames: Record<string, string> = {
  admin: 'Quản trị',
  operator: 'Vận hành',
  station_owner: 'Chủ trạm',
  driver: 'Tài xế',
  accountant: 'Kế toán',
}
export const vietnamInstant = (value: string) =>
  value ? new Date(`${value}:00+07:00`).toISOString() : ''
export function healthSegments(
  points: HealthHistory['points'],
  metric:
    | 'online_charge_points'
    | 'running_sessions'
    | 'error_messages_5m'
    | 'response_latency_ms',
) {
  const segments: { time: number; value: number; measured: string }[][] = []
  let active: { time: number; value: number; measured: string }[] = []
  for (const p of points) {
    const value = p.metrics?.[metric]
    if (value == null || !p.measured_at) {
      if (active.length) segments.push(active)
      active = []
      continue
    }
    active.push({
      time: Date.parse(p.bucket_start),
      value,
      measured: p.measured_at,
    })
  }
  if (active.length) segments.push(active)
  return segments
}
