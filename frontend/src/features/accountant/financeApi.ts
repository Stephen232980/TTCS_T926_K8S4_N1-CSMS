import { notifySessionUnauthorized } from '../auth/sessionEvents'
import { downloadCsvFile } from '../owner/ownerRevenueApi'


export const financialLabels = {
  in_progress: 'Đang sạc', awaiting_unplug: 'Chờ rút súng', needs_review: 'Cần kiểm tra',
  pending_invoice: 'Chờ lập hóa đơn', pending_settlement: 'Chờ quyết toán',
  settled: 'Đã quyết toán', legacy_exempt: 'Miễn quyết toán dữ liệu cũ',
}
export type FinancialStatus = keyof typeof financialLabels
export interface FinancialSession {
  session_id: number; station_id: string; station_name: string; charge_point_code: string;
  connector_number: number; driver_email: string | null; started_at: string; ended_at: string | null;
  connector_released_at: string | null; energy_kwh: string | null; status: FinancialStatus;
  review_reasons: string[]; invoice_id: string | null; invoice_created_at: string | null;
  invoice_total_vnd: string | null; debited_vnd: string; ledger_id: number | null;
  debited_at: string | null; settlement_completed_at: string | null; settlement_reason: string | null;
}
export interface FinancialPage {
  items: FinancialSession[]; total: number; page: number; total_pages: number;
  summary: { sessions: number; invoices: number; invoice_total_vnd: string; debited_total_vnd: string; awaiting_settlement: number };
}
export interface FinancialDetail extends FinancialSession {
  rounding_rule: string | null; ledger_amount_vnd: string | null; ledger_reference_type: string | null;
  lines: { id: string; line_type: string; local_date: string; started_at: string; ended_at: string;
    energy_kwh: string; rate_vnd: string; band_label: string; interpolated: boolean; amount_vnd: string; tariff_id: string }[];
}
export type StationOption = { id: string; name: string }
export type FinanceArea = 'sessions' | 'invoices' | 'reconciliation' | 'runs'
export const ageLabels: Record<string,string> = {under_hour:'Dưới 1 giờ',under_day:'1–24 giờ',under_week:'1–7 ngày',over_week:'Từ 7 ngày'}
export interface FinanceInsightsData {
  grain: 'day' | 'month'; generated_at: string;
  timeline: {period:string; sessions:number; invoice_vnd:string; debited_vnd:string}[];
  stations: {id:string; name:string; sessions:number; invoice_vnd:string; debited_vnd:string}[];
  statuses: {status:FinancialStatus; count:number; invoice_vnd:string}[];
  aging: {bucket:string; count:number; invoice_vnd:string}[];
  fees: {type:string; amount_vnd:string}[];
}
export const financeTitles: Record<FinanceArea, string> = {
  sessions: 'Phiên sạc & thanh toán',
  invoices: 'Hóa đơn phí sạc',
  reconciliation: 'Cần đối chiếu',
  runs: 'Đợt đối soát tổng kWh & tiền thu (S-53)',
}

export interface ReconciliationRunItem {
  id: string
  cutoff_at: string
  date_from: string
  date_to: string
  station_id: string | null
  status: 'completed' | 'failed' | 'in_progress'
  total_sessions: number
  matched_sessions: number
  mismatch_sessions: number
  missing_data_sessions: number
  exempt_sessions: number
  total_billed_vnd: string
  total_recomputed_vnd: string
  total_debited_vnd: string
  money_discrepancy_vnd: string
  total_meter_kwh: string
  total_billed_kwh: string
  kwh_discrepancy: string
  input_hash: string
  summary_counts: Record<string, number>
  executed_by_actor_id: string | null
  created_at: string
}

export interface ReconciliationRunListResponse {
  items: ReconciliationRunItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface ReconciliationIssueItem {
  id: string
  run_id: string
  session_id: number
  station_id: string | null
  station_name: string | null
  issue_category: string
  severity: 'critical' | 'warning' | 'info'
  discrepancy_amount_vnd: string
  discrepancy_kwh: string
  description: string
  evidence: Record<string, unknown>
  created_at: string
}

export interface ReconciliationIssueListResponse {
  items: ReconciliationIssueItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface CreateReconciliationRunPayload {
  date_from: string
  date_to: string
  station_id?: string | null
}

export const issueCategoryLabels: Record<string, string> = {
  missing_invoice: 'Thiếu hóa đơn',
  missing_ledger: 'Thiếu ghi nợ ví',
  ledger_mismatch: 'Lệch sổ cái ví',
  pricing_mismatch: 'Lệch đơn giá (tính lại)',
  meter_decreased: 'Số đo giảm bất thường',
  meter_missing: 'Thiếu số đo công tơ',
  meter_wh_discrepancy: 'Lệch kWh đo vs tính tiền',
  legacy_exempt: 'Miễn trừ dữ liệu cũ',
}
export const financeHints: Record<FinancialStatus, string> = {
  in_progress: 'Phiên chưa kết thúc. Số tiền chỉ được xác nhận khi có hóa đơn.',
  awaiting_unplug: 'Đã dừng cấp điện, đang chờ trụ xác nhận rút súng. Phí chiếm trụ có thể còn phát sinh.',
  pending_invoice: 'Chưa có hóa đơn được lưu. Hệ thống xử lý tự động; nếu trạng thái kéo dài, chuyển vận hành kiểm tra kèm mã phiên.',
  pending_settlement: 'Đã có hóa đơn nhưng chưa hoàn tất quyết toán. Làm mới sau khi hệ thống xử lý; không yêu cầu nạp hay trừ ví lại.',
  needs_review: 'Dữ liệu cần kiểm tra trước khi xác nhận khoản thu. Đối chiếu hóa đơn, sổ cái và lý do bên dưới; chuyển vận hành nếu liên quan trụ hoặc số đo.',
  settled: 'Quyết toán đã hoàn tất. Khoản trừ ví được đối chiếu với sổ cái; hóa đơn 0 đồng không tạo khoản trừ.',
  legacy_exempt: 'Hóa đơn dữ liệu cũ được miễn quyết toán theo mốc chuyển đổi. Tổng hóa đơn này không phải số tiền đã thu qua ví.',
}

export function money(value: string | null): string {
  if (value === null) return '—'
  try { return `${BigInt(value).toLocaleString('vi-VN')} đ` } catch { return '—' }
}
export const instant = (value: string | null) => value ? new Date(value).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' }) : '—'
export const energy = (value: string | null) => value === null ? '—' : `${Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 6 })} kWh`

export async function financeRequest<T>(path: string, signal?: AbortSignal): Promise<T> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
  const response = await fetch(`${base}/api/v1/accounting${path}`, { credentials: 'include', signal })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown }
    throw new Error(response.status === 403 ? 'Bạn không có quyền xem dữ liệu kế toán.' : response.status === 422 ? 'Bộ lọc chưa hợp lệ. Kiểm tra ngày, mã trạm và trạng thái.' : typeof body.detail === 'string' ? body.detail : 'Không tải được dữ liệu kế toán. Hãy thử lại.')
  }
  return response.json() as Promise<T>
}

export function financialQuery(hash: string): URLSearchParams {
  const source = new URLSearchParams(hash.split('?')[1])
  const result = new URLSearchParams()
  for (const key of ['q', 'station_id', 'date_from', 'date_to', 'status', 'age', 'page', 'session']) {
    const value = source.get(key)
    if (value) result.set(key, value)
  }
  const page = Number(result.get('page') ?? 1)
  result.set('page', String(Number.isSafeInteger(page) && page > 0 ? page : 1))
  return result
}

export function financeLink(area: FinanceArea, params: URLSearchParams): string {
  return `#accountant-${area}?${params}`
}

export function navigateFinance(area: FinanceArea, params: URLSearchParams) {
  window.history.pushState(window.history.state, '', financeLink(area, params))
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

export async function getReconciliationRuns(
  params?: URLSearchParams,
  signal?: AbortSignal
): Promise<ReconciliationRunListResponse> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
  const q = params && params.toString() ? `?${params.toString()}` : ''
  const response = await fetch(`${base}/api/v1/accounting/reconciliation-runs${q}`, {
    credentials: 'include',
    signal,
  })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown }
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Không tải được danh sách đợt đối soát.')
  }
  return response.json()
}

export async function createReconciliationRun(
  payload: CreateReconciliationRunPayload
): Promise<ReconciliationRunItem> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
  const response = await fetch(`${base}/api/v1/accounting/reconciliation-runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown }
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Không thể thực hiện đợt đối soát mới.')
  }
  return response.json()
}

export async function getReconciliationRunDetail(
  runId: string,
  signal?: AbortSignal
): Promise<ReconciliationRunItem> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
  const response = await fetch(`${base}/api/v1/accounting/reconciliation-runs/${encodeURIComponent(runId)}`, {
    credentials: 'include',
    signal,
  })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown }
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Không tải được chi tiết đợt đối soát.')
  }
  return response.json()
}

export async function getReconciliationRunIssues(
  runId: string,
  category?: string,
  page = 1,
  pageSize = 50,
  signal?: AbortSignal
): Promise<ReconciliationIssueListResponse> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (category) params.set('issue_category', category)
  const response = await fetch(
    `${base}/api/v1/accounting/reconciliation-runs/${encodeURIComponent(runId)}/issues?${params}`,
    {
      credentials: 'include',
      signal,
    }
  )
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown }
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Không tải được danh sách sai lệch đối soát.')
  }
  return response.json()
}

export async function exportAccountantRevenueCsv(
  params: {
    period?: string
    date_from?: string
    date_to?: string
    station_id?: string
  } = {}
): Promise<void> {
  const query = new URLSearchParams()
  if (params.period) query.set('period', params.period)
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)
  if (params.station_id) query.set('station_id', params.station_id)

  const qs = query.toString()
  const path = `/accounting/reports/revenue/export${qs ? `?${qs}` : ''}`
  await downloadCsvFile(path, 'revenue_report.csv')
}

export async function exportReconciliationIssuesCsv(
  runId: string,
  severity?: string,
  issueType?: string
): Promise<void> {
  const params = new URLSearchParams()
  if (severity) params.set('severity', severity)
  if (issueType) params.set('issue_type', issueType)

  const qs = params.toString()
  const path = `/accounting/reconciliation-runs/${encodeURIComponent(runId)}/issues/export${qs ? `?${qs}` : ''}`
  await downloadCsvFile(path, `reconciliation_issues_${runId}.csv`)
}


