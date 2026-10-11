import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WalletTopUpPage } from './WalletTopUpPage'
import { WalletTopUpApiError } from './walletTopUpApi'

const created = { order_id: 'order-001', redirect_url: 'http://localhost:8001/fake-gateway/order-001' }

describe('T-94 - Màn hình nạp tiền', () => {
  it('hiển thị số tiền mặc định và mức nạp đang được chọn', () => {
    render(<WalletTopUpPage onTopUp={vi.fn()} />)
    expect((screen.getByLabelText('Số tiền nạp (VNĐ)') as HTMLInputElement).value).toBe('100000')
    expect(screen.getByRole('button', { name: '100.000đ' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('không cho nạp dưới 10.000 VNĐ và liên kết lỗi với input', async () => {
    const user = userEvent.setup()
    const onTopUp = vi.fn()
    render(<WalletTopUpPage onTopUp={onTopUp} />)
    const input = screen.getByLabelText('Số tiền nạp (VNĐ)')
    await user.clear(input)
    await user.type(input, '5000')
    expect(screen.getByRole('button', { name: 'Nạp tiền' }).hasAttribute('disabled')).toBe(true)
    expect(input.getAttribute('aria-describedby')).toBe('topup-validation')
    expect(onTopUp).not.toHaveBeenCalled()
  })

  it('chọn số tiền, tạo pending và chuyển đúng redirect_url của backend', async () => {
    const user = userEvent.setup()
    const onTopUp = vi.fn(async () => created)
    const onRedirect = vi.fn()
    render(<WalletTopUpPage onTopUp={onTopUp} onRedirect={onRedirect} />)
    await user.click(screen.getByRole('button', { name: '200.000đ' }))
    expect(screen.getByRole('button', { name: '200.000đ' }).getAttribute('aria-pressed')).toBe('true')
    await user.click(screen.getByRole('button', { name: 'Nạp tiền' }))
    await waitFor(() => expect(onRedirect).toHaveBeenCalledWith(created.redirect_url))
    expect(onTopUp).toHaveBeenCalledTimes(1)
    expect(onTopUp).toHaveBeenCalledWith(200000)
    expect(screen.getByRole('button', { name: /Đang chuyển/ }).hasAttribute('disabled')).toBe(true)
  })

  it('không gửi lại trong khi POST đang treo', async () => {
    const user = userEvent.setup()
    let complete!: (value: typeof created) => void
    const onTopUp = vi.fn(() => new Promise<typeof created>(resolve => { complete = resolve }))
    render(<WalletTopUpPage onTopUp={onTopUp} onRedirect={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Nạp tiền' }))
    fireEvent.submit(screen.getByRole('button', { name: 'Đang tạo lệnh...' }).closest('form')!)
    expect(onTopUp).toHaveBeenCalledTimes(1)
    complete(created)
    await waitFor(() => expect(screen.getByRole('button', { name: /Đang chuyển/ })).toBeTruthy())
  })

  it('giữ order_id khi lỗi POST và chỉ tra trạng thái, không POST lại', async () => {
    const user = userEvent.setup()
    const onTopUp = vi.fn().mockRejectedValue(new WalletTopUpApiError('uncertain', 'Chưa xác định giao dịch.', 500, 'order-123'))
    const onCheckOrder = vi.fn()
    render(<WalletTopUpPage onTopUp={onTopUp} onCheckOrder={onCheckOrder} />)
    await user.click(screen.getByRole('button', { name: 'Nạp tiền' }))
    expect(await screen.findByText(/order-123/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Nạp tiền' }).hasAttribute('disabled')).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Kiểm tra trạng thái đơn này' }))
    expect(onCheckOrder).toHaveBeenCalledWith('order-123')
    expect(onTopUp).toHaveBeenCalledTimes(1)
  })

  it('gateway navigation lỗi: vẫn giữ order_id để tra cứu, không POST lại', async () => {
    const user = userEvent.setup()
    const onTopUp = vi.fn().mockResolvedValue(created)
    const onCheckOrder = vi.fn()
    render(<WalletTopUpPage onTopUp={onTopUp} onCheckOrder={onCheckOrder}
      onRedirect={() => { throw new Error('Navigation blocked') }} />)
    await user.click(screen.getByRole('button', { name: 'Nạp tiền' }))
    expect(await screen.findByText(/order-001/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Nạp tiền' }).hasAttribute('disabled')).toBe(true)
    expect(onTopUp).toHaveBeenCalledTimes(1)
  })

  it('mất mạng không rõ kết quả thì không tự POST lại', async () => {
    const user = userEvent.setup()
    const onTopUp = vi.fn().mockRejectedValue(new WalletTopUpApiError('uncertain', 'Không rõ kết quả'))
    render(<WalletTopUpPage onTopUp={onTopUp} />)
    await user.click(screen.getByRole('button', { name: 'Nạp tiền' }))
    expect(await screen.findByText(/Không rõ kết quả/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Nạp tiền' }).hasAttribute('disabled')).toBe(true)
  })
})
