import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AdminManualTopup } from './AdminManualTopup'
import { AdminWorkspace } from './AdminWorkspace'
const driver = { id: 'driver-id', email: 'driver@example.com', roles: ['driver'], status: 'active' }
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
const post = vi.fn()
let fetcher: ReturnType<typeof vi.fn>
const payload = (index = 0) => JSON.parse(post.mock.calls[index][1].body)
const resultFor = (body: ReturnType<typeof payload>) => ({ ledger_id: 12, driver_id: driver.id, actor_id: 'admin-1', amount_vnd: body.amount_vnd, balance_after_vnd: 150000, receipt_code: 'PT-AUTO-' + body.request_id.replaceAll('-', ''), request_id: body.request_id, payment_received: true, external_reference: body.external_reference ?? null, created_at: '2026-10-10T01:00:00Z' })
beforeEach(() => {
 sessionStorage.clear()
 post.mockReset().mockImplementation(async (_url: string, options: RequestInit) => response(resultFor(JSON.parse(String(options.body))), 201))
 fetcher = vi.fn((url: string, options?: RequestInit) => options?.method === 'POST' ? post(url, options) : Promise.resolve(response({ items: [driver], page: 1, total: 1, total_pages: 1 })))
 vi.stubGlobal('fetch', fetcher); window.history.replaceState(null, '', '/')
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); sessionStorage.clear() })
async function fill(mount = true, reference = ' CHUNG-TU-001 ') {
 if (mount) render(<AdminManualTopup adminId="admin-1" />)
 fireEvent.click(await screen.findByRole('radio', { name: driver.email }))
 fireEvent.change(screen.getByLabelText('Số tiền (VND)'), { target: { value: '100000' } })
 fireEvent.change(screen.getByLabelText('Tham chiếu chứng từ (không bắt buộc)'), { target: { value: reference } })
}
function confirm() {
 fireEvent.click(screen.getByRole('button', { name: 'Tiếp tục kiểm tra' }))
 fireEvent.click(screen.getByRole('checkbox'))
 fireEvent.click(screen.getByRole('button', { name: 'Xác nhận nạp tiền' }))
}
it('generates a UUID only after payment confirmation and sends the new contract without receipt_code', async () => {
 const uuid = vi.spyOn(crypto, 'randomUUID'); await fill()
 expect(String(fetcher.mock.calls[0][0])).toContain('role=driver&status=active')
 fireEvent.click(screen.getByRole('button', { name: 'Tiếp tục kiểm tra' }))
 expect(post).not.toHaveBeenCalled(); expect(uuid).not.toHaveBeenCalled()
 expect(screen.getByRole('button', { name: 'Xác nhận nạp tiền' })).toBeDisabled()
 fireEvent.click(screen.getByRole('checkbox')); fireEvent.click(screen.getByRole('button', { name: 'Xác nhận nạp tiền' }))
 await screen.findByText(/Đã nạp 100.000 VND/)
 expect(post).toHaveBeenCalledOnce()
 expect(post.mock.calls[0][0]).toBe('/api/v1/admin/drivers/driver-id/wallet/manual-topups')
 expect(payload()).toEqual({ amount_vnd: 100000, request_id: expect.stringMatching(/^[0-9a-f-]{36}$/), payment_received: true, external_reference: 'CHUNG-TU-001' })
 expect(screen.getByText(/PT-AUTO-/)).toBeInTheDocument()
 expect(screen.getByText('admin-1')).toBeInTheDocument()
 expect(screen.getByText(/Số dư trên phiếu là số dư tại thời điểm/)).toBeInTheDocument()
})
it('omits an empty optional reference', async () => {
 await fill(true, '   '); confirm(); await screen.findByText(/Đã nạp/)
 expect(payload()).not.toHaveProperty('external_reference'); expect(payload()).not.toHaveProperty('receipt_code')
})
it('rejects fractional and unsafe amounts', async () => {
 await fill()
 for (const amount of ['1.5', '9007199254740992', '0', '-1']) {
  fireEvent.change(screen.getByLabelText('Số tiền (VND)'), { target: { value: amount } })
  fireEvent.click(screen.getByRole('button', { name: 'Tiếp tục kiểm tra' }))
  expect(screen.getByText('Nhập số tiền nguyên dương bằng VND.')).toBeInTheDocument()
 }
 expect(post).not.toHaveBeenCalled()
})
it('sends once and freezes confirmation during repeated clicks', async () => {
 let resolve!: (value: Response) => void
 post.mockImplementation(() => new Promise<Response>(done => { resolve = done }))
 await fill(); confirm(); fireEvent.click(screen.getByRole('button', { name: 'Đang nạp tiền…' }))
 expect(post).toHaveBeenCalledOnce()
 expect(screen.getByRole('button', { name: 'Quay lại chỉnh sửa' })).toBeDisabled(); expect(screen.getByRole('checkbox')).toBeDisabled()
 resolve(response(resultFor(payload()), 201)); await screen.findByText(/Đã nạp/)
})
it('retains the exact key and body after lost response and remount', async () => {
 post.mockRejectedValueOnce(new TypeError('Failed to fetch'))
 await fill(); confirm(); await screen.findByText(/Chưa xác định được kết quả nạp/)
 const original = payload()
 expect(screen.getByRole('button', { name: 'Quay lại chỉnh sửa' })).toBeDisabled()
 cleanup(); render(<AdminManualTopup adminId="admin-1" />)
 expect(screen.getByRole('checkbox')).toBeChecked()
 fireEvent.click(screen.getByRole('button', { name: 'Thử lại cùng khoản thu' }))
 await screen.findByText(/Đã nạp/)
 expect(payload(1)).toEqual(original); expect(sessionStorage.getItem('csms:manual-topup:admin-1')).toBeNull()
})
it('keeps request identity after a timeout without automatic retries', async () => {
 await fill()
 post.mockImplementation((_url: string, options: RequestInit) => new Promise((_resolve, reject) => options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))))
 vi.useFakeTimers(); confirm()
 await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
 expect(screen.getByText(/Chưa xác định được kết quả nạp/)).toBeInTheDocument(); expect(post).toHaveBeenCalledOnce()
 expect(JSON.parse(sessionStorage.getItem('csms:manual-topup:admin-1')!).requestId).toBe(payload().request_id)
 expect(screen.getByRole('button', { name: 'Thử lại cùng khoản thu' })).toBeEnabled()
})
it('blocks request conflicts without changing key or retrying', async () => {
 const uuid = vi.spyOn(crypto, 'randomUUID')
 post.mockResolvedValue(response({ detail: 'manual_topup_request_conflict' }, 409))
 await fill(); confirm(); await screen.findByText(/Mã yêu cầu đã được dùng/)
 expect(screen.getByRole('button', { name: 'Thử lại cùng khoản thu' })).toBeDisabled()
 expect(screen.getByRole('button', { name: 'Quay lại chỉnh sửa' })).toBeDisabled()
 expect(uuid).toHaveBeenCalledOnce(); expect(post).toHaveBeenCalledOnce()
})
it('allows corrections after validation rejection while retaining original identity', async () => {
 post.mockResolvedValueOnce(response({ detail: [{ loc: ['body', 'amount_vnd'], msg: 'Amount exceeds limit' }] }, 422))
 await fill(); confirm(); await screen.findByText('Dữ liệu chưa hợp lệ. Quay lại để sửa thông tin.')
 const key = payload().request_id
 fireEvent.click(screen.getByRole('button', { name: 'Quay lại chỉnh sửa' }))
 expect(screen.getByLabelText('Số tiền (VND)')).toHaveAttribute('aria-invalid', 'true')
 fireEvent.change(screen.getByLabelText('Số tiền (VND)'), { target: { value: '50000' } })
 confirm(); await screen.findByText(/Đã nạp/); expect(payload(1).request_id).toBe(key)
})
it('uses a new UUID only for a new receipt after success', async () => {
 await fill(); confirm(); await screen.findByText(/Đã nạp/); const oldKey = payload().request_id
 fireEvent.click(screen.getByRole('button', { name: 'Ghi nhận khoản thu mới' }))
 await fill(false); confirm(); await screen.findByText(/Đã nạp/); expect(payload(1).request_id).not.toBe(oldKey)
})
it('does not send when persistence is unavailable', async () => {
 await fill(); vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage blocked') }); confirm()
 expect(screen.getByText(/Không lưu được mã yêu cầu/)).toBeInTheDocument(); expect(post).not.toHaveBeenCalled()
})
it('does not restore another admin receipt', async () => {
 post.mockRejectedValueOnce(new TypeError('Failed to fetch')); await fill(); confirm(); await screen.findByText(/Chưa xác định được kết quả nạp/)
 cleanup(); render(<AdminManualTopup adminId="admin-2" />)
 expect(screen.queryByRole('button', { name: 'Thử lại cùng khoản thu' })).not.toBeInTheDocument()
 expect(screen.getByRole('button', { name: 'Tiếp tục kiểm tra' })).toBeInTheDocument()
})
it('hides workspace and sends no request for non-admin', () => {
 window.location.hash = '#admin-topup'
 render(<AdminWorkspace currentUser={{ id: driver.id, email: driver.email, roles: ['driver'] }} onLogout={async () => {}} />)
 expect(screen.queryByText('Nạp tiền thủ công')).not.toBeInTheDocument(); expect(fetcher).not.toHaveBeenCalled()
})
it('ignores stale driver search responses', async () => {
 let resolve!: (value: Response) => void
 fetcher.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done }))
 render(<AdminManualTopup adminId="admin-1" />); await waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
 fireEvent.change(screen.getByLabelText('Tìm tài xế theo email'), { target: { value: 'driver@' } })
 await screen.findByRole('radio', { name: driver.email })
 resolve(response({ items: [{ ...driver, email: 'stale@example.com' }], page: 1, total: 1, total_pages: 1 }))
 await waitFor(() => expect(screen.queryByText('stale@example.com')).not.toBeInTheDocument())
})
