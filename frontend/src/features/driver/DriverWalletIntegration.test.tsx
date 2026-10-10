import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DriverWorkspace } from './DriverWorkspace'
import { WalletTopUpApiError } from './walletTopUpApi'

vi.mock('./DriverCharging', () => ({ DriverCharging: () => null }))
vi.mock('./DriverMapPage', () => ({ DriverMapPage: () => null }))
vi.mock('./walletTopUpApi', async importOriginal => {
  const original = await importOriginal<typeof import('./walletTopUpApi')>()
  return { ...original, createWalletTopUp: vi.fn(), getWalletTopUp: vi.fn(), refreshDriverWallet: vi.fn() }
})

import { createWalletTopUp, getWalletTopUp, refreshDriverWallet } from './walletTopUpApi'

const driver = { id: 'driver-1', email: 'driver@test.local', roles: ['driver'] }
const created = { order_id: 'order-001', redirect_url: 'http://gateway.test/pay/order-001' }

afterEach(() => {
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
})

describe('T-94 - DriverWorkspace end-to-end wiring', () => {
  it('nút ví POST API, sau đó chuyển đúng redirect_url', async () => {
    vi.mocked(createWalletTopUp).mockResolvedValue(created)
    const redirect = vi.fn()
    const user = userEvent.setup()
    render(<DriverWorkspace currentUser={driver} onLogout={vi.fn()} navigateToPayment={redirect} />)
    await user.click(screen.getByRole('link', { name: 'Ví của tôi' }))
    await user.click(screen.getByRole('button', { name: 'Nạp tiền' }))
    await waitFor(() => expect(redirect).toHaveBeenCalledWith(created.redirect_url))
    expect(createWalletTopUp).toHaveBeenCalledTimes(1)
    expect(createWalletTopUp).toHaveBeenCalledWith(100000)
    expect(refreshDriverWallet).not.toHaveBeenCalled()
  })

  it('detail.order_id: không tạo đơn mới, mở đọc trạng thái đúng mã', async () => {
    vi.mocked(createWalletTopUp).mockRejectedValue(new WalletTopUpApiError('uncertain', 'Không rõ kết quả', 500, 'order-err'))
    vi.mocked(getWalletTopUp).mockResolvedValue({ status: 'pending' })
    const user = userEvent.setup()
    render(<DriverWorkspace currentUser={driver} onLogout={vi.fn()} navigateToPayment={vi.fn()} />)
    await user.click(screen.getByRole('link', { name: 'Ví của tôi' }))
    await user.click(screen.getByRole('button', { name: 'Nạp tiền' }))
    await user.click(await screen.findByRole('button', { name: 'Kiểm tra trạng thái đơn này' }))
    await waitFor(() => expect(getWalletTopUp).toHaveBeenCalledWith('order-err', expect.any(AbortSignal)))
    expect(createWalletTopUp).toHaveBeenCalledTimes(1)
  })

  it('URL quay về: lấy order_code, chỉ GET và refresh ví sau succeeded', async () => {
    window.history.replaceState(null, '', '/?order_code=order-return&status=success#driver-wallet')
    vi.mocked(getWalletTopUp).mockResolvedValue({ status: 'succeeded' })
    vi.mocked(refreshDriverWallet).mockResolvedValue(undefined)
    render(<DriverWorkspace currentUser={driver} onLogout={vi.fn()} navigateToPayment={vi.fn()} />)
    await waitFor(() => expect(getWalletTopUp).toHaveBeenCalledWith('order-return', expect.any(AbortSignal)))
    await waitFor(() => expect(refreshDriverWallet).toHaveBeenCalledTimes(1))
    expect(createWalletTopUp).not.toHaveBeenCalled()
    expect(screen.getByText(/Backend đã xác nhận nạp tiền thành công/)).toBeTruthy()
  })
})
