import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Station } from '../model/station'
import { StationList } from './StationList'

const station: Station = {
  id: 'station-1',
  name: 'Trạm Quận 1',
  address: '123 Nguyễn Huệ, Quận 1, TP.HCM',
  latitude: 10.7731,
  longitude: 106.7032,
  status: 'active',
  createdAt: '2026-09-20T08:30:00Z',
  updatedAt: '2026-09-20T08:30:00Z',
}

const defaultProps = {
  stations: [station],
  isLoading: false,
  error: '',
  onView: () => undefined,
  onEdit: () => undefined,
  onClearFilters: () => undefined,
  onRetry: () => undefined,
  canManageStations: true,
}

describe('StationList', () => {
  it('renders the loading state', () => {
    render(<StationList {...defaultProps} stations={[]} isLoading />)

    expect(screen.getByLabelText('Đang tải danh sách trạm')).toBeInTheDocument()
  })

  it('renders the error state and retries', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    render(
      <StationList
        {...defaultProps}
        stations={[]}
        error="Không thể tải danh sách trạm."
        onRetry={onRetry}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Thử lại' }))

    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('renders the empty state and clears filters', async () => {
    const user = userEvent.setup()
    const onClearFilters = vi.fn()
    render(
      <StationList
        {...defaultProps}
        stations={[]}
        onClearFilters={onClearFilters}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Không tìm thấy trạm' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Xóa bộ lọc' }))

    expect(onClearFilters).toHaveBeenCalledOnce()
  })

  it('renders responsive station views and reports edit actions', async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn()
    render(<StationList {...defaultProps} onEdit={onEdit} />)

    expect(screen.getAllByText('Trạm Quận 1')).toHaveLength(2)
    await user.click(
      screen.getByRole('button', { name: 'Chỉnh sửa Trạm Quận 1' }),
    )

    expect(onEdit).toHaveBeenCalledWith(station)
  })

  it('opens station details from the station name', async () => {
    const user = userEvent.setup()
    const onView = vi.fn()
    render(<StationList {...defaultProps} onView={onView} />)

    await user.click(
      screen.getByRole('button', { name: 'Xem chi tiết Trạm Quận 1' }),
    )

    expect(onView).toHaveBeenCalledWith(station)
  })

  it('keeps the read-only list free of edit actions', () => {
    render(<StationList {...defaultProps} canManageStations={false} />)

    expect(screen.getAllByText('Trạm Quận 1')).toHaveLength(2)
    expect(
      screen.queryByRole('button', { name: /Chỉnh sửa/ }),
    ).not.toBeInTheDocument()
  })

  it.each([
    ['suspended', 'Tạm ngưng'],
    ['blocked', 'Đã khóa'],
  ] as const)('renders the %s station status', (status, label) => {
    render(
      <StationList
        {...defaultProps}
        stations={[{ ...station, status }]}
      />,
    )

    expect(screen.getAllByText(label)).toHaveLength(2)
  })
})
