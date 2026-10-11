import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChargingSessionsPage } from './ChargingSessionsPage'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const transaction = { id: 42, station_name: 'Trạm Quận 1', charge_point_code: 'CP-01', connector_number: 1, tag_tail: 'ABCD', authorization_status: 'Accepted', started_at: '2026-10-02T01:00:00Z', ended_at: null, meter_start_wh: '1000', meter_stop_wh: null, energy_kwh: null, latest_meter_wh: '2000', latest_meter_at: '2026-10-02T01:01:00Z', stop_reason: null, review_reasons: ['meter_regression'] }
const page = { items: [transaction], total: 1, page: 1, total_pages: 1 }
function response(data: unknown) { return { ok: true, status: 200, json: async () => data } }

describe('ChargingSessionsPage', () => {
  it('filters abnormal sessions, closes using the real API and displays history', async () => {
    let closed = false
    const fetch = vi.fn().mockImplementation(async (url: string, options: RequestInit) => {
      if (options.method === 'POST') { closed = true; return response({ energy_kwh: '1' }) }
      if (url.endsWith('/events')) return response([{ id: 'e1', action: 'manual_closure', actor: 'operator@example.com', details: { reason: 'Đã kiểm tra', energy_kwh: '1' }, occurred_at: '2026-10-02T02:00:00Z' }])
      return response({ ...page, items: [{ ...transaction, abnormal_since: closed ? null : '2026-10-02T01:10:00Z', ended_at: closed ? '2026-10-02T02:00:00Z' : null, energy_kwh: closed ? '1' : null }] })
    })
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()
    render(<ChargingSessionsPage canClose />)
    await screen.findByText('Phiên #42')
    await user.selectOptions(screen.getByLabelText('Trạng thái phiên'), 'abnormal')
    await user.click(await screen.findByRole('button', { name: 'Đóng tay phiên 42' }))
    await user.type(screen.getByLabelText('Lý do đóng tay'), 'Đã kiểm tra')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Xác nhận đóng phiên' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Đã đóng phiên #42, chốt 1 kWh')
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/sessions/42/close'), expect.objectContaining({ method: 'POST', body: JSON.stringify({ reason: 'Đã kiểm tra' }) }))
    await user.click(screen.getByRole('button', { name: 'Xem lịch sử phục hồi phiên 42' }))
    expect(await screen.findByText('Đóng tay bằng số đo cuối')).toBeInTheDocument()
    expect(screen.getByText(/operator@example.com/)).toBeInTheDocument()
  })

  it('hides management and manual closure for accounting access', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ...page, items: [{ ...transaction, abnormal_since: '2026-10-02T01:10:00Z' }] })))
    render(<ChargingSessionsPage canManage={false} canClose={false} />)
    await screen.findByText('Phiên #42')
    expect(screen.queryByRole('button', { name: 'Thẻ tài xế' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Chờ đối chiếu' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Đóng tay phiên 42' })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Bất thường — chưa kết thúc' })).toBeInTheDocument()
  })

  it('shows history loading errors and retries', async () => {
    let retried = false
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith('/events')) { if (!retried) return { ok: false, status: 500, json: async () => ({}) }; return response([]) }
      return response(page)
    }))
    const user = userEvent.setup()
    render(<ChargingSessionsPage />)
    await screen.findByText('Phiên #42')
    await user.click(screen.getByRole('button', { name: 'Xem lịch sử phục hồi phiên 42' }))
    await screen.findByRole('button', { name: 'Tải lại lịch sử' })
    retried = true
    await user.click(screen.getByRole('button', { name: 'Tải lại lịch sử' }))
    expect(await screen.findByText('Chưa có sự kiện phục hồi.')).toBeInTheDocument()
  })
  it('loads real API, shows review reasons and fetches meter detail', async () => {
    const fetch = vi.fn().mockImplementation(async (url: string) => response(url.includes('/samples') ? { items: [{ timestamp: '2026-10-02T01:01:00Z', measurand: 'Energy.Active.Import.Register', value: '2000', unit: 'Wh', phase: '', location: 'Outlet' }], total: 1, page: 1, total_pages: 1 } : page))
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()
    render(<ChargingSessionsPage />)
    expect(await screen.findByText('Phiên #42')).toBeInTheDocument()
    expect(screen.getByText('Số đo điện năng giảm')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Xem biểu đồ phiên 42' }))
    expect(await screen.findByRole('img', { name: /Biểu đồ điện năng tích lũy phiên 42/ })).toBeInTheDocument()
    await user.click(screen.getByText('Thông tin phiên và bảng số đo'))
    expect(screen.getByText('…ABCD')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/sessions/42/samples'), expect.objectContaining({ credentials: 'include' }))
  })

  it('creates a driver card, clears the identifying input and locks the card', async () => {
    const card = { id: 'card1', tag_tail: 'ABCD', driver_email: 'driver@example.com', status: 'active', expires_at: null }
    const fetch = vi.fn().mockImplementation(async (url: string, options: RequestInit) => response(options.method ? card : url.endsWith('/cards') ? [card] : page))
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()
    render(<ChargingSessionsPage />)
    await screen.findByText('Phiên #42')
    await user.click(screen.getByRole('button', { name: 'Thẻ tài xế' }))
    await user.type(screen.getByLabelText('Mã thẻ'), 'TEST-ABCD')
    await user.type(screen.getByLabelText('Email tài xế'), 'driver@example.com')
    await user.click(screen.getByRole('button', { name: 'Cấp thẻ' }))
    await screen.findByText('Đã cấp thẻ. Hãy dùng mã thẻ đã nhập để quẹt tại trụ.')
    expect(screen.getByLabelText('Mã thẻ')).toHaveValue('')
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/cards'), expect.objectContaining({ method: 'POST', body: JSON.stringify({ id_tag: 'TEST-ABCD', driver_email: 'driver@example.com', expires_at: null }) }))
    await user.click(await screen.findByRole('button', { name: 'Khóa thẻ' }))
    await screen.findByText('Đã cập nhật trạng thái thẻ.')
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/cards/card1'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ status: 'blocked' }) }))
  })

  it('shows pending reconciliation without a fake repair action', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => response(url.endsWith('/pending') ? [{ id: 'pending1', charge_point_code: 'CP-01', action: 'StopTransaction', reason: 'unknown_transaction', transaction_id: 99, received_at: '2026-10-02T01:00:00Z' }] : page)))
    const user = userEvent.setup()
    render(<ChargingSessionsPage />)
    await screen.findByText('Phiên #42')
    await user.click(screen.getByRole('button', { name: 'Chờ đối chiếu' }))
    expect(await screen.findByText('Không tìm thấy phiên · Phiên #99')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Đóng phiên' })).not.toBeInTheDocument()
  })

  it('retries loading errors and aborts pending requests on unmount', async () => {
    const fetch = vi.fn().mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) }).mockResolvedValue(response(page))
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()
    const view = render(<ChargingSessionsPage />)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('Phiên #42')).toBeInTheDocument()
    const options = fetch.mock.lastCall?.[1] as RequestInit
    view.unmount()
    expect(options.signal?.aborted).toBe(true)
  })

  it('refreshes a closed transaction and uses server-side state filtering', async () => {
    let closed = false
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => response({ ...page, items: [{ ...transaction, ended_at: closed ? '2026-10-02T02:00:00Z' : null, energy_kwh: closed ? '2.5' : null }] })))
    const user = userEvent.setup()
    render(<ChargingSessionsPage />)
    await screen.findByText('Phiên #42')
    closed = true
    await user.click(screen.getByRole('button', { name: 'Làm mới' }))
    expect(await screen.findByText('Đã kết thúc', { selector: 'span' })).toBeInTheDocument()
    expect(await screen.findByText('2,5 kWh')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Trạng thái phiên'), 'review')
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('state=review'), expect.anything()))
  })
})

