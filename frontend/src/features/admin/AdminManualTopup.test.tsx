import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AdminManualTopup } from './AdminManualTopup'
import { AdminWorkspace } from './AdminWorkspace'

const driver = {
  id: 'driver-id',
  email: 'driver@example.com',
  roles: ['driver'],
  status: 'active',
}
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
const post = vi.fn()
let fetcher: ReturnType<typeof vi.fn>
beforeEach(() => {
  post
    .mockReset()
    .mockResolvedValue(
      response(
        {
          ledger_id: 12,
          amount_vnd: 100000,
          balance_after_vnd: 150000,
          receipt_code: 'PT-01',
          created_at: '2026-10-10T01:00:00Z',
        },
        201,
      ),
    )
  fetcher = vi.fn((url: string, options?: RequestInit) =>
    options?.method === 'POST'
      ? post(url, options)
      : Promise.resolve(
          response({ items: [driver], page: 1, total: 1, total_pages: 1 }),
        ),
  )
  vi.stubGlobal('fetch', fetcher)
  window.location.hash = ''
})
afterEach(() => vi.unstubAllGlobals())
async function fill() {
  render(<AdminManualTopup />)
  fireEvent.click(await screen.findByRole('radio', { name: driver.email }))
  fireEvent.change(screen.getByLabelText('Số tiền (VND)'), {
    target: { value: '100000' },
  })
  fireEvent.change(screen.getByLabelText('Mã phiếu thu'), {
    target: { value: ' PT-01 ' },
  })
}
it('filters active drivers and requires two confirmations before sending the exact amount and receipt', async () => {
  await fill()
  expect(String(fetcher.mock.calls[0][0])).toContain(
    'role=driver&status=active',
  )
  fireEvent.click(screen.getByText('Tiếp tục kiểm tra'))
  expect(post).not.toHaveBeenCalled()
  expect(screen.getByText('100.000 VND')).toBeInTheDocument()
  expect(screen.getByText('PT-01')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Xác nhận nạp tiền' }))
  await screen.findByText(/Đã nạp 100.000 VND/)
  expect(post).toHaveBeenCalledOnce()
  expect(post.mock.calls[0][0]).toBe(
    '/api/v1/admin/drivers/driver-id/wallet/manual-topups',
  )
  expect(JSON.parse(post.mock.calls[0][1].body)).toEqual({
    amount_vnd: 100000,
    receipt_code: 'PT-01',
  })
  expect(screen.getByLabelText('Mã phiếu thu')).toHaveValue('')
})
it('blocks missing receipt inline and rejects fractional or unsafe amounts', async () => {
  await fill()
  fireEvent.change(screen.getByLabelText('Mã phiếu thu'), {
    target: { value: '   ' },
  })
  fireEvent.change(screen.getByLabelText('Số tiền (VND)'), {
    target: { value: '1.5' },
  })
  fireEvent.click(screen.getByText('Tiếp tục kiểm tra'))
  expect(screen.getByText('Vui lòng nhập mã phiếu thu.')).toBeInTheDocument()
  expect(
    screen.getByText('Nhập số tiền nguyên dương bằng VND.'),
  ).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Số tiền (VND)'), {
    target: { value: '9007199254740992' },
  })
  fireEvent.click(screen.getByText('Tiếp tục kiểm tra'))
  expect(post).not.toHaveBeenCalled()
  expect(
    screen.queryByRole('button', { name: 'Xác nhận nạp tiền' }),
  ).not.toBeInTheDocument()
})
it('sends one POST during repeated clicks and freezes review while pending', async () => {
  let resolve!: (value: Response) => void
  post.mockImplementation(
    () =>
      new Promise<Response>((done) => {
        resolve = done
      }),
  )
  await fill()
  fireEvent.click(screen.getByText('Tiếp tục kiểm tra'))
  const confirm = screen.getByRole('button', { name: 'Xác nhận nạp tiền' })
  fireEvent.click(confirm)
  fireEvent.click(confirm)
  expect(post).toHaveBeenCalledOnce()
  expect(screen.getByText('Quay lại chỉnh sửa')).toBeDisabled()
  resolve(
    response(
      {
        ledger_id: 12,
        amount_vnd: 100000,
        balance_after_vnd: 150000,
        receipt_code: 'PT-01',
        created_at: '2026-10-10T01:00:00Z',
      },
      201,
    ),
  )
  await screen.findByText(/Đã nạp/)
})
it.each([
  ['receipt_already_used', 'Mã phiếu thu đã được sử dụng.'],
  ['wallet_locked', 'Ví tài xế đang bị khóa.'],
])('explains conflict %s without automatic retries', async (code, message) => {
  post.mockResolvedValue(response({ detail: code }, 409))
  await fill()
  fireEvent.click(screen.getByText('Tiếp tục kiểm tra'))
  fireEvent.click(screen.getByText('Xác nhận nạp tiền', { selector: 'button' }))
  await screen.findByText(new RegExp(message))
  expect(post).toHaveBeenCalledOnce()
})
it('maps server amount limit validation back to the amount field', async () => {
  post.mockResolvedValue(
    response(
      {
        detail: [
          {
            loc: ['body', 'amount_vnd'],
            msg: 'Amount exceeds manual topup limit',
          },
        ],
      },
      422,
    ),
  )
  await fill()
  fireEvent.click(screen.getByText('Tiếp tục kiểm tra'))
  fireEvent.click(screen.getByText('Xác nhận nạp tiền', { selector: 'button' }))
  await screen.findByText('Dữ liệu chưa hợp lệ. Quay lại để sửa thông tin.')
  fireEvent.click(screen.getByText('Quay lại chỉnh sửa'))
  expect(screen.getByLabelText('Số tiền (VND)')).toHaveAttribute(
    'aria-invalid',
    'true',
  )
  expect(screen.getByText(/vượt hạn mức/)).toBeInTheDocument()
})
it('keeps receipt after uncertain network result and never retries automatically', async () => {
  post.mockRejectedValue(new TypeError('Failed to fetch'))
  await fill()
  fireEvent.click(screen.getByText('Tiếp tục kiểm tra'))
  fireEvent.click(screen.getByText('Xác nhận nạp tiền', { selector: 'button' }))
  await screen.findByText(/giữ nguyên mã phiếu thu/)
  expect(post).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByText('Quay lại chỉnh sửa'))
  expect(screen.getByLabelText('Mã phiếu thu')).toHaveValue(' PT-01 ')
})
it('hides the workspace and makes no request for non-admin even with a topup hash', () => {
  window.location.hash = '#admin-topup'
  render(
    <AdminWorkspace
      currentUser={{ id: 'driver-id', email: driver.email, roles: ['driver'] }}
      onLogout={async () => {}}
    />,
  )
  expect(screen.queryByText('Nạp tiền thủ công')).not.toBeInTheDocument()
  expect(fetcher).not.toHaveBeenCalled()
})
it('ignores stale search results after a newer query', async () => {
  let resolve!: (value: Response) => void
  fetcher.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done
      }),
  )
  render(<AdminManualTopup />)
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
  fireEvent.change(screen.getByLabelText('Tìm tài xế theo email'), {
    target: { value: 'driver@' },
  })
  await screen.findByRole('radio', { name: driver.email })
  resolve(
    response({
      items: [{ ...driver, email: 'stale@example.com' }],
      page: 1,
      total: 1,
      total_pages: 1,
    }),
  )
  await waitFor(() =>
    expect(screen.queryByText('stale@example.com')).not.toBeInTheDocument(),
  )
})
