
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WalletTopUpPage } from './WalletTopUpPage'

describe('T-94 - Màn hình nạp tiền', () => {
  it('hiển thị số tiền mặc định', () => {
    render(<WalletTopUpPage onTopUp={vi.fn()} />)

    expect(
      (screen.getByLabelText('Số tiền nạp (VNĐ)') as HTMLInputElement)
        .value,
    ).toBe('100000')
  })

  it('không cho nạp dưới 10.000 VNĐ', async () => {
    const user = userEvent.setup()
    const onTopUp = vi.fn()

    render(<WalletTopUpPage onTopUp={onTopUp} />)

    const input = screen.getByLabelText('Số tiền nạp (VNĐ)')

    await user.clear(input)
    await user.type(input, '5000')

    expect(
      screen.getByRole('button', { name: 'Nạp tiền' })
        .hasAttribute('disabled'),
    ).toBe(true)
  })

  it('gửi đúng số tiền khi nạp', async () => {
    const user = userEvent.setup()
    const onTopUp = vi.fn(async () => {})

    render(<WalletTopUpPage onTopUp={onTopUp} />)

    await user.click(
      screen.getByRole('button', { name: '200.000đ' }),
    )

    await user.click(
      screen.getByRole('button', { name: 'Nạp tiền' }),
    )

    expect(onTopUp).toHaveBeenCalledWith(200000)
  })
})
