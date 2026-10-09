
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TariffForm } from './TariffForm'

describe('T-62 - Form khai báo biểu giá', () => {
  it('hiển thị biểu giá hiện hành', () => {
    render(
      <TariffForm
        currentTariff={{
          pricePerKwh: 3500,
          idleFeePerMinute: 500,
          graceMinutes: 5,
        }}
        onSave={vi.fn()}
      />,
    )

    expect(screen.getByText(/3.500 VNĐ\/kWh/)).toBeTruthy()
    expect(screen.getByText(/500 VNĐ\/phút/)).toBeTruthy()
  })

  it('báo lỗi khi nhập số âm', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()

    render(
      <TariffForm currentTariff={null} onSave={onSave} />,
    )

    const input = screen.getByLabelText(
      'Đơn giá mỗi kWh (VNĐ)',
    )

    await user.type(input, '-100')

    expect(
      screen.getByRole('alert').textContent,
    ).toContain('Chỉ được nhập số nguyên không âm.')

    expect(
      screen.getByRole('button', {
        name: 'Lưu biểu giá',
      }).hasAttribute('disabled'),
    ).toBe(true)
  })

  it('gửi đúng dữ liệu hợp lệ khi lưu', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(async () => {})

    render(
      <TariffForm currentTariff={null} onSave={onSave} />,
    )

    await user.type(
      screen.getByLabelText('Đơn giá mỗi kWh (VNĐ)'),
      '3500',
    )

    await user.type(
      screen.getByLabelText('Phí chiếm trụ mỗi phút (VNĐ)'),
      '500',
    )

    await user.type(
      screen.getByLabelText('Thời gian ân hạn (phút)'),
      '5',
    )

    await user.click(
      screen.getByRole('button', {
        name: 'Lưu biểu giá',
      }),
    )

    expect(onSave).toHaveBeenCalledWith({
      pricePerKwh: 3500,
      idleFeePerMinute: 500,
      graceMinutes: 5,
    })
  })
})
