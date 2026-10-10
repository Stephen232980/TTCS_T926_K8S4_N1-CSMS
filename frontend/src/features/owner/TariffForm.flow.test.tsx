
import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TariffForm } from './TariffForm'
import { OwnerApiError } from './ownerApi'

async function fillForm(user: ReturnType<typeof userEvent.setup>) {
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
}

describe('T-62 - Luồng lưu biểu giá', () => {
  it('API lỗi 422: giữ dữ liệu, hiện lỗi đúng ô và cho thử lại', async () => {
    const user = userEvent.setup()

    const onSave = vi.fn()
      .mockRejectedValueOnce(
        new OwnerApiError(422, [
          {
            loc: ['body', 'grace_minutes'],
            msg: 'Ân hạn không hợp lệ',
          },
        ]),
      )
      .mockResolvedValueOnce(undefined)

    render(
      <TariffForm
        stationTimezone="Asia/Ho_Chi_Minh"
        currentTariff={null}
        onSave={onSave}
      />,
    )

    await fillForm(user)

    await user.click(
      screen.getByRole('button', { name: 'Lưu biểu giá' }),
    )

    expect(
      await screen.findByText('Ân hạn không hợp lệ'),
    ).toBeTruthy()

    expect(
      (screen.getByLabelText(
  'Thời gian ân hạn (phút)',
  { exact: false },
) as HTMLInputElement).value,
    ).toBe('5')

    expect(
      screen.queryByText(/Đã lưu biểu giá vào hệ thống/),
    ).toBeNull()

   const graceInput = screen.getByLabelText(
  'Thời gian ân hạn (phút)',
  { exact: false },
)

    await user.clear(graceInput)
    await user.type(graceInput, '6')

    await user.click(
      screen.getByRole('button', { name: 'Lưu biểu giá' }),
    )

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledTimes(2)
      expect(
        screen.getByText(/Đã lưu biểu giá vào hệ thống/),
      ).toBeTruthy()
    })
  })

  it('chặn ân hạn vượt giới hạn tại ô nhập', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()

    render(
      <TariffForm
        stationTimezone="Asia/Ho_Chi_Minh"
        currentTariff={null}
        onSave={onSave}
      />,
    )

    await fillForm(user)

    const graceInput = screen.getByLabelText(
      'Thời gian ân hạn (phút)',
    )

    await user.clear(graceInput)
    await user.type(graceInput, '2147483648')

    expect(
      screen.getByText('Giá trị vượt phạm vi cho phép.'),
    ).toBeTruthy()

    expect(
      screen.getByRole('button', {
        name: 'Lưu biểu giá',
      }).hasAttribute('disabled'),
    ).toBe(true)

    expect(onSave).not.toHaveBeenCalled()
  })

  it('khóa nút lưu khi đang gửi và chỉ tạo một request', async () => {
    const user = userEvent.setup()

    let resolveSave!: () => void

    const pending = new Promise<void>((resolve) => {
      resolveSave = resolve
    })

    const onSave = vi.fn(() => pending)

    const { container } = render(
      <TariffForm
        stationTimezone="Asia/Ho_Chi_Minh"
        currentTariff={null}
        onSave={onSave}
      />,
    )

    await fillForm(user)

    await user.click(
      screen.getByRole('button', { name: 'Lưu biểu giá' }),
    )

    expect(
      screen.getByRole('button', {
        name: 'Đang lưu...',
      }).hasAttribute('disabled'),
    ).toBe(true)

    // Thử gửi lần nữa khi request đầu chưa kết thúc.
    fireEvent.submit(container.querySelector('form')!)

    expect(onSave).toHaveBeenCalledTimes(1)

    await act(async () => {
      resolveSave()
      await pending
    })

    expect(
      await screen.findByText(/Đã lưu biểu giá vào hệ thống/),
    ).toBeTruthy()
  })
})
