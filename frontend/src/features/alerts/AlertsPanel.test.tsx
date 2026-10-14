import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ownerRequest } from '../owner/ownerApi'
import { AlertsPanel } from './AlertsPanel'

vi.mock('../owner/ownerApi', () => ({ ownerRequest: vi.fn() }))
const request = vi.mocked(ownerRequest)
const item = { id: 'alert-1', charge_point_code: 'DEMO-01', station_name: 'Trạm trung tâm',
  kind: 'offline', status: 'open', opened_at: '2026-10-14T01:00:00Z', recovered_at: null,
  close_reason: null, email_status: 'failed', email_attempts: 6 }
const page = { items: [item], total: 1, page: 1, total_pages: 1, generated_at: '2026-10-14T01:00:15Z' }

beforeEach(() => { request.mockReset(); request.mockResolvedValue(page) })
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

describe('G3 operational alerts', () => {
  it('shows real incident and email status, acknowledges then reloads', async () => {
    render(<AlertsPanel area="ops" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Tiếp nhận DEMO-01' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/ops/alerts/alert-1/acknowledge', expect.objectContaining({ method: 'POST' })))
    expect(await screen.findByText('Đã tiếp nhận cảnh báo.')).toBeInTheDocument()
    expect(screen.getByText(/Email gửi thất bại/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Đóng DEMO-01' })).not.toBeInTheDocument()
  })

  it('owner only reads owned alerts and never sees mutation controls', async () => {
    render(<AlertsPanel area="owner" />)
    await screen.findByText(/Ngoại tuyến quá ngưỡng/)
    expect(request).toHaveBeenCalledWith('/owner/alerts?status=active&page=1', expect.anything())
    expect(screen.queryByRole('button', { name: /Tiếp nhận|Thử lại email|Đóng DEMO/ })).not.toBeInTheDocument()
  })

  it('requires an admin reason to force-close a continuing incident', async () => {
    render(<AlertsPanel area="admin" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Đóng DEMO-01' }))
    const reason = screen.getByRole('textbox', { name: 'Lý do đóng DEMO-01' })
    expect(reason).toBeRequired()
    expect(reason).toHaveFocus()
    fireEvent.change(reason, { target: { value: 'Đã lên lịch bảo trì' } })
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận đóng' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/admin/alerts/alert-1/close', expect.objectContaining({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: true, reason: 'Đã lên lịch bảo trì' }) })))
  })

  it('retains visible incidents and reports failed updates without showing a healthy empty state', async () => {
    render(<AlertsPanel area="ops" />)
    await screen.findByText(/Ngoại tuyến quá ngưỡng/)
    request.mockRejectedValueOnce(new Error('offline'))
    fireEvent.click(screen.getByRole('button', { name: 'Tải lại cảnh báo' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('có thể đã cũ')
    expect(screen.getByText(/Ngoại tuyến quá ngưỡng/)).toBeInTheDocument()
    expect(screen.queryByText('Không có cảnh báo đang mở.')).not.toBeInTheDocument()
  })

  it('polls every 10 seconds and pauses while the tab is hidden', async () => {
    vi.useFakeTimers()
    render(<AlertsPanel area="ops" />)
    await act(async () => { await Promise.resolve() })
    expect(request).toHaveBeenCalledTimes(1)
    await act(async () => { vi.advanceTimersByTime(10000); await Promise.resolve() })
    expect(request).toHaveBeenCalledTimes(2)
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    await act(async () => { vi.advanceTimersByTime(20000); await Promise.resolve() })
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('does not restore an old poll response after a successful acknowledgement', async () => {
    let resolveOld: (value: unknown) => void = () => undefined
    request.mockResolvedValueOnce(page).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    render(<AlertsPanel area="ops" />)
    await screen.findByText(/Ngoại tuyến quá ngưỡng/)
    fireEvent.click(screen.getByRole('button', { name: 'Tải lại cảnh báo' }))
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
    request.mockResolvedValueOnce({ status: 'acknowledged' }).mockResolvedValue({ ...page, items: [{ ...item, status: 'acknowledged' }] })
    fireEvent.click(screen.getByRole('button', { name: 'Tiếp nhận DEMO-01' }))
    await screen.findByText(/Đã tiếp nhận/)
    await act(async () => { resolveOld(page); await Promise.resolve() })
    expect(screen.queryByRole('button', { name: 'Tiếp nhận DEMO-01' })).not.toBeInTheDocument()
  })

  it('resets to the last available page after incidents are closed', async () => {
    request.mockResolvedValueOnce({ ...page, total: 51, total_pages: 2 })
    render(<AlertsPanel area="ops" />)
    await screen.findByText('Trang 1/2')
    request.mockResolvedValueOnce({ ...page, page: 2, total: 51, total_pages: 2 })
    fireEvent.click(screen.getByRole('button', { name: 'Trang sau' }))
    await screen.findByText('Trang 2/2')
    request.mockResolvedValue({ ...page, page: 1, total: 1, total_pages: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'Tải lại cảnh báo' }))
    await waitFor(() => expect(request).toHaveBeenLastCalledWith('/ops/alerts?status=active&page=1', expect.anything()))
    expect(screen.queryByText('Không có cảnh báo đang mở.')).not.toBeInTheDocument()
    expect(screen.getByText(/Ngoại tuyến quá ngưỡng/)).toBeInTheDocument()
  })
})
