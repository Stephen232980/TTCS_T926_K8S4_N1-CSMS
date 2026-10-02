vi.mock('../../../components/maps/StationMap', () => ({ StationMap: ({ onPick }: { onPick?: (p: { latitude: number; longitude: number }) => void }) => <button type="button" onClick={() => onPick?.({ latitude: 10.7731, longitude: 106.7032 })}>Chọn vị trí thử</button> }))
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Station } from '../model/station'
import { StationForm } from './StationForm'

const station: Station = {
  id: 'station-1',
  name: 'Trạm Quận 1',
  address: '123 Nguyễn Huệ, Quận 1',
  latitude: 10.7731,
  longitude: 106.7032,
  status: 'inactive',
  createdAt: '2026-09-29T10:00:00Z',
  updatedAt: '2026-09-29T10:00:00Z',
}

describe('StationForm', () => {
  it('shows field-level errors and focuses the first invalid field', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(
      <StationForm mode="create" onSubmit={onSubmit} onCancel={() => undefined} />,
    )

    await user.click(screen.getByRole('button', { name: 'Tạo trạm' }))

    expect(screen.getByLabelText('Tên trạm')).toHaveFocus()
    expect(screen.getByText('Tên trạm là bắt buộc')).toBeInTheDocument()
    expect(screen.getByText('Địa chỉ là bắt buộc')).toBeInTheDocument()
    expect(screen.getByText('Hãy chọn vị trí trạm trên bản đồ.')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits trimmed valid values', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(
      <StationForm mode="create" onSubmit={onSubmit} onCancel={() => undefined} />,
    )

    await user.type(screen.getByLabelText('Tên trạm'), '  Trạm Quận 1  ')
    await user.type(
      screen.getByLabelText('Địa chỉ'),
      '  123 Nguyễn Huệ, Quận 1  ',
    )
    await user.click(screen.getByRole('button', { name: 'Chọn vị trí thử' }))
    await user.click(screen.getByRole('button', { name: 'Tạo trạm' }))

    expect(onSubmit).toHaveBeenCalledWith({
      name: 'Trạm Quận 1',
      address: '123 Nguyễn Huệ, Quận 1',
      latitude: 10.7731,
      longitude: 106.7032,
    })
  })

  it('prefills an edit form and exposes the submit error', () => {
    render(
      <StationForm
        mode="edit"
        station={station}
        submitError="Không thể lưu thay đổi. Vui lòng thử lại."
        onSubmit={() => undefined}
        onCancel={() => undefined}
      />,
    )

    expect(screen.getByLabelText('Tên trạm')).toHaveValue('Trạm Quận 1')
    expect(screen.getByLabelText('Địa chỉ')).toHaveValue(
      '123 Nguyễn Huệ, Quận 1',
    )
    expect(screen.getByText('Đã chọn vị trí trạm. Bạn có thể chọn lại trên bản đồ.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Vĩ độ')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Không thể lưu thay đổi. Vui lòng thử lại.',
    )
  })

  it('disables the form while submitting', () => {
    render(
      <StationForm
        mode="create"
        isSubmitting
        onSubmit={() => undefined}
        onCancel={() => undefined}
      />,
    )

    expect(screen.getByLabelText('Tên trạm')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Đang lưu…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Hủy' })).toBeDisabled()
  })
})
