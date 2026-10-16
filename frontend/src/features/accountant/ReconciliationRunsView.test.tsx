import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ReconciliationRunsView } from './ReconciliationRunsView'
import type { ReconciliationIssueItem, ReconciliationRunItem } from './financeApi'

const mockRun: ReconciliationRunItem = {
  id: 'run-12345678-abcd',
  cutoff_at: '2026-10-15T12:00:00Z',
  date_from: '2026-10-01',
  date_to: '2026-10-15',
  station_id: null,
  status: 'completed',
  total_sessions: 10,
  matched_sessions: 8,
  mismatch_sessions: 2,
  missing_data_sessions: 0,
  exempt_sessions: 0,
  total_billed_vnd: '200000',
  total_recomputed_vnd: '190000',
  total_debited_vnd: '200000',
  money_discrepancy_vnd: '10000',
  total_meter_kwh: '50.000000',
  total_billed_kwh: '50.000000',
  kwh_discrepancy: '0.000000',
  input_hash: 'abc123def4567890abcdef1234567890abcdef1234567890abcdef1234567890',
  summary_counts: {
    pricing_mismatch: 1,
    missing_invoice: 1,
  },
  executed_by_actor_id: 'actor-1',
  created_at: '2026-10-15T12:05:00Z',
}

const mockIssue: ReconciliationIssueItem = {
  id: 'issue-1',
  run_id: 'run-12345678-abcd',
  session_id: 101,
  station_id: 'st-1',
  station_name: 'Trạm Landmark',
  issue_category: 'pricing_mismatch',
  severity: 'critical',
  discrepancy_amount_vnd: '10000',
  discrepancy_kwh: '0.000000',
  description: 'Hóa đơn 200.000 đ nhưng tính lại theo biểu giá ra 190.000 đ',
  evidence: {
    billed_total_vnd: 200000,
    recomputed_total_vnd: 190000,
    diff_vnd: 10000,
  },
  created_at: '2026-10-15T12:05:01Z',
}

function mockApi() {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes('/reconciliation-runs') && options?.method === 'POST') {
      return new Response(JSON.stringify(mockRun), { status: 201 })
    }
    if (url.includes('/issues')) {
      return new Response(
        JSON.stringify({
          items: [mockIssue],
          total: 1,
          page: 1,
          page_size: 50,
          total_pages: 1,
        }),
        { status: 200 }
      )
    }
    if (url.includes('/reconciliation-runs/run-12345678-abcd')) {
      return new Response(JSON.stringify(mockRun), { status: 200 })
    }
    if (url.includes('/reconciliation-runs')) {
      return new Response(
        JSON.stringify({
          items: [mockRun],
          total: 1,
          page: 1,
          page_size: 20,
          total_pages: 1,
        }),
        { status: 200 }
      )
    }
    return new Response(JSON.stringify({ items: [] }), { status: 200 })
  })
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}

beforeEach(() => {
  vi.stubGlobal('scrollTo', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('renders reconciliation runs list and shows run metrics', async () => {
  mockApi()
  render(<ReconciliationRunsView stations={[]} />)

  expect(await screen.findByRole('heading', { name: /Đợt đối soát tổng kWh/ })).toBeInTheDocument()
  expect(await screen.findByText('Đợt #run-1234')).toBeInTheDocument()
  expect(screen.getByText('10.000 đ')).toBeInTheDocument()
  expect(screen.getByText('Có sai lệch')).toBeInTheDocument()
})

it('opens form and validates date bounds before creating run', async () => {
  const fetcher = mockApi()
  const user = userEvent.setup()
  render(<ReconciliationRunsView stations={[{ id: 'st-1', name: 'Trạm Landmark' }]} />)

  await screen.findByText('Đợt #run-1234')
  await user.click(screen.getByRole('button', { name: '+ Tạo đợt đối soát mới' }))

  expect(screen.getByRole('heading', { name: 'Tạo đợt đối soát snapshot mới' })).toBeInTheDocument()

  // Reverse dates to test validation
  fireEvent.change(screen.getByLabelText(/Từ ngày/), { target: { value: '2026-10-31' } })
  fireEvent.change(screen.getByLabelText(/Đến ngày/), { target: { value: '2026-10-01' } })
  await user.click(screen.getByRole('button', { name: 'Chạy đối soát ngay' }))

  expect(screen.getByRole('alert')).toHaveTextContent('Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.')
  expect(fetcher.mock.calls.some(([, opt]) => opt?.method === 'POST')).toBe(false)

  // Fix dates and submit
  fireEvent.change(screen.getByLabelText(/Từ ngày/), { target: { value: '2026-10-01' } })
  fireEvent.change(screen.getByLabelText(/Đến ngày/), { target: { value: '2026-10-15' } })
  await user.click(screen.getByRole('button', { name: 'Chạy đối soát ngay' }))

  await waitFor(() =>
    expect(fetcher.mock.calls.some(([, opt]) => opt?.method === 'POST')).toBe(true)
  )
})

it('drills down into a run detail, displays KPIs and issues table', async () => {
  mockApi()
  const user = userEvent.setup()
  render(<ReconciliationRunsView stations={[]} />)

  await user.click(await screen.findByRole('button', { name: /Xem chi tiết/ }))

  expect(await screen.findByRole('heading', { name: /Đợt đối soát #run-1234/ })).toBeInTheDocument()
  expect(screen.getByText(/abc123def4567890/)).toBeInTheDocument()
  expect(screen.getByText('Lệch đơn giá (tính lại) (1)')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Phiên #101' })).toBeInTheDocument()
  expect(screen.getByText('Trạm Landmark')).toBeInTheDocument()
})

it('copies issue evidence to clipboard with feedback', async () => {
  mockApi()
  const user = userEvent.setup()
  const clipboard = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
  render(<ReconciliationRunsView stations={[]} />)

  await user.click(await screen.findByRole('button', { name: /Xem chi tiết/ }))
  await screen.findByRole('link', { name: 'Phiên #101' })

  await user.click(screen.getByRole('button', { name: 'Sao chép hồ sơ' }))
  expect(clipboard).toHaveBeenCalledWith(expect.stringContaining('Phiên #101'))
  expect(await screen.findByText('Đã sao chép để chuyển vận hành')).toBeInTheDocument()
})
