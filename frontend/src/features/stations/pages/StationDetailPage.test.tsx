import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { StationApiError } from '../api/httpStationApi'
import { MockStationApi } from '../api/mockStationApi'
import type { Station } from '../model/station'
import { StationDetailPage } from './StationDetailPage'

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

describe('StationDetailPage', () => {
  it('loads and renders station details', async () => {
    render(
      <StationDetailPage
        stationId={station.id}
        onBack={() => undefined}
        api={new MockStationApi([station], 0)}
      />,
    )

    expect(
      screen.getByLabelText('Đang tải chi tiết trạm'),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', { name: station.name }),
    ).toBeInTheDocument()
    expect(screen.getByText(station.address)).toBeInTheDocument()
    expect(screen.getByText('10.773100')).toBeInTheDocument()
    expect(screen.getByText('106.703200')).toBeInTheDocument()
  })

  it('returns to the station list', async () => {
    const user = userEvent.setup()
    const onBack = vi.fn()
    render(
      <StationDetailPage
        stationId={station.id}
        onBack={onBack}
        api={new MockStationApi([station], 0)}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Quay lại danh sách trạm' }))

    expect(onBack).toHaveBeenCalledOnce()
  })

  it('shows a permission error and retries', async () => {
    const user = userEvent.setup()
    const api = new MockStationApi([station], 0)
    const getStation = vi
      .spyOn(api, 'getStation')
      .mockRejectedValueOnce(new StationApiError(403, 'permission_denied'))
      .mockResolvedValueOnce(station)

    render(
      <StationDetailPage
        stationId={station.id}
        onBack={() => undefined}
        api={api}
      />,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Bạn không có quyền xem trạm này.',
    )
    await user.click(screen.getByRole('button', { name: 'Thử lại' }))

    expect(
      await screen.findByRole('heading', { name: station.name }),
    ).toBeInTheDocument()
    expect(getStation).toHaveBeenCalledTimes(2)
  })
})
