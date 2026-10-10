import { notifySessionUnauthorized } from '../auth/sessionEvents'

export type InvoiceStatus = 'ready' | 'pending' | 'needs_review' | 'in_progress'
export interface InvoiceSummary {
  session_id: number
  station_name: string
  ended_at: string | null
  status: InvoiceStatus
  total_vnd: string | null
}
export interface InvoiceLine {
  id: string
  line_type: 'energy' | 'idle'
  local_date: string
  started_at: string
  ended_at: string
  energy_kwh: string
  rate_vnd: string
  band_label: string
  interpolated: boolean
  tariff_id: string
  amount_vnd: string
}
export interface DriverInvoice extends InvoiceSummary {
  invoice_id: string | null
  created_at: string | null
  rounding_rule: string | null
  lines: InvoiceLine[]
}
export interface InvoiceList { items: InvoiceSummary[]; next_cursor: number | null }
export interface DriverInvoiceApi {
  list(cursor?: number, signal?: AbortSignal): Promise<InvoiceList>
  get(sessionId: number, signal?: AbortSignal): Promise<DriverInvoice>
}
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${base}/api/v1/driver${path}`, { credentials: 'include', signal })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) throw new Error(response.status === 403
    ? 'Bạn không có quyền xem hóa đơn này.'
    : response.status === 404 ? 'Không tìm thấy phiên sạc.'
    : response.status === 401 ? 'Phiên đăng nhập đã hết hạn.' : 'Không tải được hóa đơn. Vui lòng thử lại.')
  return response.json() as Promise<T>
}
export const driverInvoiceApi: DriverInvoiceApi = {
  list: (cursor, signal) => read(`/invoices${cursor ? `?cursor=${cursor}` : ''}`, signal),
  get: (id, signal) => read(`/charging/sessions/${encodeURIComponent(id)}/invoice`, signal),
}
export const invoiceMoney = (value: string) => `${new Intl.NumberFormat('vi-VN').format(BigInt(value))} đ`
