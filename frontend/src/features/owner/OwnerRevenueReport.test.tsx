import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnerRevenueReport } from './OwnerRevenueReport'
import type { RevenueReportResponse } from './ownerRevenueApi'

const mockReport: RevenueReportResponse = {
  from_date: '2026-11-01T00:00:00+07:00',
  to_date: '2026-12-01T00:00:00+07:00',
  timezone: 'Asia/Ho_Chi_Minh',
  summary: {
    invoiced_sessions: 4,
    total_kwh: '120.5',
    energy_amount_vnd: 420000,
    idle_amount_vnd: 30000,
    total_invoice_vnd: 450000,
    debited_vnd: 350000,
    awaiting_settlement_vnd: 100000,
    unbilled_sessions: 1,
    unbilled_operating_kwh: '25.0',
  },
  charge_points: [
    {
      station_id: 'sta-1',
      station_name: 'Trạm Landmark',
      charge_point_id: 'cp-1',
      charge_point_code: 'CP-LANDMARK-01',
      sessions_count: 3,
      energy_kwh: '90.5',
      energy_amount_vnd: 315000,
      idle_amount_vnd: 25000,
      total_invoice_vnd: 340000,
      debited_vnd: 340000,
      awaiting_settlement_vnd: 0,
      unbilled_sessions: 0,
      unbilled_operating_kwh: '0',
    },
    {
      station_id: 'sta-1',
      station_name: 'Trạm Landmark',
      charge_point_id: 'cp-2',
      charge_point_code: 'CP-LANDMARK-02',
      sessions_count: 1,
      energy_kwh: '30.0',
      energy_amount_vnd: 105000,
      idle_amount_vnd: 5000,
      total_invoice_vnd: 110000,
      debited_vnd: 10000,
      awaiting_settlement_vnd: 100000,
      unbilled_sessions: 1,
      unbilled_operating_kwh: '25.0',
    },
  ],
  daily_timeline: [
    {
      date: '2026-11-01',
      sessions_count: 1,
      kwh: '30.0',
      invoice_vnd: 110000,
      debited_vnd: 10000,
    },
    {
      date: '2026-11-02',
      sessions_count: 3,
      kwh: '90.5',
      invoice_vnd: 340000,
      debited_vnd: 340000,
    },
  ],
  pagination: {
    page: 1,
    page_size: 50,
    total_items: 2,
    total_pages: 1,
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('renders default monthly revenue report with summary cards, chart and table', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(mockReport))),
  )

  render(<OwnerRevenueReport />)

  // Loading indicator first
  expect(screen.getByRole('status')).toHaveTextContent('Đang tải dữ liệu báo cáo')

  // Summary cards loaded
  await waitFor(() => {
    expect(screen.getByText('Tổng doanh thu hóa đơn')).toBeInTheDocument()
  })

  // Format VND check
  expect(screen.getByText(/450\.000/)).toBeInTheDocument()
  expect(screen.getByText(/350\.000/)).toBeInTheDocument()
  expect(screen.getAllByText(/100\.000/).length).toBeGreaterThanOrEqual(1)

  // Energy & Sessions check
  expect(screen.getByText(/120,5 kWh/)).toBeInTheDocument()
  expect(screen.getByText(/4 phiên/)).toBeInTheDocument()

  // Unbilled operating kWh check
  expect(screen.getAllByText(/25,0 kWh/).length).toBeGreaterThanOrEqual(1)

  // Charge points table
  expect(screen.getByText('CP-LANDMARK-01')).toBeInTheDocument()
  expect(screen.getByText('CP-LANDMARK-02')).toBeInTheDocument()
  expect(screen.getAllByText(/340\.000/).length).toBeGreaterThanOrEqual(1)
})

it('allows switching period to day, week and custom', async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(mockReport)))
  vi.stubGlobal('fetch', fetchMock)

  const user = userEvent.setup()
  render(<OwnerRevenueReport />)

  await screen.findByText('Tổng doanh thu hóa đơn')

  // Switch to 'Hôm nay'
  await user.click(screen.getByRole('button', { name: 'Hôm nay' }))
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('period=day'),
      expect.anything(),
    )
  })

  // Switch to 'Tuần này'
  await user.click(screen.getByRole('button', { name: 'Tuần này' }))
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('period=week'),
      expect.anything(),
    )
  })

  // Switch to 'Tùy chọn' shows date pickers
  await user.click(screen.getByRole('button', { name: 'Tùy chọn' }))
  expect(screen.getByLabelText('Từ ngày')).toBeInTheDocument()
  expect(screen.getByLabelText('Đến ngày')).toBeInTheDocument()
})

it('displays error alert on API failure and allows retry', async () => {
  let shouldFail = true
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      if (shouldFail) {
        return new Response(JSON.stringify({ detail: 'Lỗi máy chủ' }), {
          status: 500,
        })
      }
      return new Response(JSON.stringify(mockReport))
    }),
  )

  const user = userEvent.setup()
  render(<OwnerRevenueReport />)

  await screen.findByRole('alert')
  expect(screen.getByText(/Không tải hoặc lưu được dữ liệu/)).toBeInTheDocument()

  shouldFail = false
  await user.click(screen.getByRole('button', { name: 'Thử lại' }))

  await waitFor(() => {
    expect(screen.getByText('Tổng doanh thu hóa đơn')).toBeInTheDocument()
  })
})

it('displays empty message when period has no charging data', async () => {
  const emptyReport: RevenueReportResponse = {
    ...mockReport,
    summary: {
      invoiced_sessions: 0,
      total_kwh: '0',
      energy_amount_vnd: 0,
      idle_amount_vnd: 0,
      total_invoice_vnd: 0,
      debited_vnd: 0,
      awaiting_settlement_vnd: 0,
      unbilled_sessions: 0,
      unbilled_operating_kwh: '0',
    },
    charge_points: [],
    daily_timeline: [],
    pagination: {
      page: 1,
      page_size: 50,
      total_items: 0,
      total_pages: 1,
    },
  }

  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(emptyReport))),
  )

  render(<OwnerRevenueReport />)

  await screen.findByText(
    'Không có dữ liệu phiên sạc hoặc doanh thu trong kỳ đã chọn.',
  )
  expect(screen.getByText('Tổng doanh thu hóa đơn')).toBeInTheDocument()
})

it('triggers CSV export when Xuất CSV button is clicked', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/export')) {
      return new Response('\ufeffperiod_from,period_to\n', {
        headers: {
          'Content-Type': 'text/csv; charset=utf-8',
          'Content-Disposition':
            'attachment; filename="revenue_report_20261101_20261201.csv"',
        },
      })
    }
    return new Response(JSON.stringify(mockReport))
  })
  vi.stubGlobal('fetch', fetchMock)
  window.URL.createObjectURL = vi.fn(() => 'blob:mock-url')
  window.URL.revokeObjectURL = vi.fn()

  render(<OwnerRevenueReport />)

  await screen.findByText('Tổng doanh thu hóa đơn')

  const exportBtn = screen.getByRole('button', {
    name: 'Xuất CSV báo cáo doanh thu',
  })
  expect(exportBtn).toBeInTheDocument()
  await user.click(exportBtn)

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/owner/reports/revenue/export'),
      expect.objectContaining({ credentials: 'include' }),
    )
  })
})

