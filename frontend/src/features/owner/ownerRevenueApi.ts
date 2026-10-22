import { ownerRequest } from './ownerApi'

export type PeriodType = 'day' | 'week' | 'month' | 'custom'

export interface RevenueReportParams {
  period?: PeriodType
  date_from?: string
  date_to?: string
  station_id?: string
  charge_point_id?: string
  page?: number
  page_size?: number
}

export interface RevenueSummary {
  invoiced_sessions: number
  total_kwh: string | number
  energy_amount_vnd: number
  idle_amount_vnd: number
  total_invoice_vnd: number
  debited_vnd: number
  awaiting_settlement_vnd: number
  unbilled_sessions: number
  unbilled_operating_kwh: string | number
}

export interface ChargePointRevenueItem {
  station_id: string
  station_name: string
  charge_point_id: string
  charge_point_code: string
  sessions_count: number
  energy_kwh: string | number
  energy_amount_vnd: number
  idle_amount_vnd: number
  total_invoice_vnd: number
  debited_vnd: number
  awaiting_settlement_vnd: number
  unbilled_sessions: number
  unbilled_operating_kwh: string | number
}

export interface DailyRevenueItem {
  date: string
  sessions_count: number
  kwh: string | number
  invoice_vnd: number
  debited_vnd: number
}

export interface PaginationMeta {
  page: number
  page_size: number
  total_items: number
  total_pages: number
}

export interface RevenueReportResponse {
  from_date: string
  to_date: string
  timezone: string
  summary: RevenueSummary
  charge_points: ChargePointRevenueItem[]
  daily_timeline: DailyRevenueItem[]
  pagination: PaginationMeta
}

export function formatVnd(amount: number): string {
  return new Intl.NumberFormat('vi-VN', {
    style: 'currency',
    currency: 'VND',
    maximumFractionDigits: 0,
  }).format(amount)
}

export function formatKwh(kwh: string | number): string {
  const num = typeof kwh === 'string' ? parseFloat(kwh) : kwh
  if (isNaN(num)) return '0 kWh'
  return `${new Intl.NumberFormat('vi-VN', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  }).format(num)} kWh`
}

export async function fetchRevenueReport(
  params: RevenueReportParams = {},
): Promise<RevenueReportResponse> {
  const query = new URLSearchParams()
  if (params.period) query.set('period', params.period)
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)
  if (params.station_id) query.set('station_id', params.station_id)
  if (params.charge_point_id) query.set('charge_point_id', params.charge_point_id)
  if (params.page) query.set('page', String(params.page))
  if (params.page_size) query.set('page_size', String(params.page_size))

  const qs = query.toString()
  const path = `/owner/reports/revenue${qs ? `?${qs}` : ''}`
  return ownerRequest<RevenueReportResponse>(path)
}
