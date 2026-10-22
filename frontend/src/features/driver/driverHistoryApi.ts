import { notifySessionUnauthorized } from '../auth/sessionEvents'

export type HistoryState = 'all' | 'open' | 'closed' | 'review' | 'abnormal'
export interface HistorySession {
  id: number; station_id: string; station_name: string; charge_point_code: string
  connector_number: number; started_at: string; ended_at: string | null
  energy_kwh: string | number | null; latest_meter_wh: string | number | null
  meter_start_wh: string | number; review_reasons: string[]; abnormal_since: string | null
}
export interface HistoryPage { items: HistorySession[]; total: number; page: number; total_pages: number }
export interface SessionDetail {
  id: number; station_name: string; charge_point_code: string; connector_number: number
  started_at: string; ended_at: string | null; energy_kwh: string | number | null
  elapsed_seconds: number; needs_attention: boolean; awaiting_unplug?: boolean
}
export interface HistoryRoute { page: number; state: HistoryState; session?: number; invoice: boolean }
export const historyStates: Record<HistoryState, string> = {
  all: 'Tất cả trạng thái', open: 'Chưa kết thúc', closed: 'Đã kết thúc', review: 'Cần kiểm tra', abnormal: 'Gián đoạn',
}
export function readHistoryRoute(): HistoryRoute {
  const query = new URLSearchParams(window.location.hash.split('?')[1])
  const page = Number(query.get('page')), session = Number(query.get('session'))
  const state = query.get('state') ?? 'all'
  return { page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    state: Object.hasOwn(historyStates, state) ? state as HistoryState : 'all',
    session: Number.isSafeInteger(session) && session > 0 ? session : undefined,
    invoice: query.get('view') === 'invoice' }
}
export function historyLink(route: HistoryRoute): string {
  const query = new URLSearchParams({ page: String(route.page), state: route.state })
  if (route.session) query.set('session', String(route.session))
  if (route.invoice && route.session) query.set('view', 'invoice')
  return `#driver-history?${query}`
}
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
export async function readHistory<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${base}/api/v1${path}`, { credentials: 'include', signal })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) throw new Error(response.status === 401 ? 'Phiên đăng nhập đã hết hạn.'
    : response.status === 403 ? 'Bạn không có quyền xem dữ liệu phiên sạc này.'
    : response.status === 404 ? 'Không tìm thấy phiên sạc.' : 'Không tải được lịch sử phiên sạc. Vui lòng thử lại.')
  return response.json() as Promise<T>
}
const dateFormat = new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short', timeZone: 'Asia/Ho_Chi_Minh' })
export function historyDate(value: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return '—'
  return dateFormat.format(new Date(value))
}
export function historyEnergy(value: string | number | null): string {
  if (value === null || !Number.isFinite(Number(value))) return 'Chưa có số đo'
  return `${new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 3 }).format(Number(value))} kWh`
}
export function historyStatus(item: HistorySession): string {
  return item.ended_at ? 'Đã kết thúc' : item.abnormal_since ? 'Gián đoạn' : 'Chưa kết thúc'
}
