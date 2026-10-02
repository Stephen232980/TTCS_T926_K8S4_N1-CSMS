import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MockChargePointApi } from '../../chargePoints/api/mockChargePointApi'
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
  it.each([false, true])('shows the create form only with permission (%s)', async (canManageChargePoints) => {
    const chargePointApi = new MockChargePointApi([], 0)
    const checkCode = vi.spyOn(chargePointApi, 'checkCodeAvailability')
    render(<StationDetailPage stationId={station.id} onBack={() => undefined}
      api={new MockStationApi([station], 0)} chargePointApi={chargePointApi}
      canManageChargePoints={canManageChargePoints} />)
    await screen.findByRole('heading', { name: station.name })
    expect(screen.queryByRole('heading', { name: 'Thêm trụ sạc' }) !== null).toBe(canManageChargePoints)
    if (!canManageChargePoints) {
      expect(screen.queryByLabelText('Mã trụ')).not.toBeInTheDocument()
      expect(checkCode).not.toHaveBeenCalled()
    }
  })

  it('loads and renders station details', async () => {
    render(
      <StationDetailPage
        stationId={station.id}
        onBack={() => undefined}
        api={new MockStationApi([station], 0)}
        chargePointApi={new MockChargePointApi([], 0)}
      />,
    )

    expect(
      screen.getByLabelText('Đang tải chi tiết trạm'),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', { name: station.name }),
    ).toBeInTheDocument()
    expect(screen.getByText(station.address)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Bản đồ trạm sạc' })).toBeInTheDocument()
    expect(screen.queryByText('Vĩ độ')).not.toBeInTheDocument()
  })

  it('returns to the station list', async () => {
    const user = userEvent.setup()
    const onBack = vi.fn()
    render(
      <StationDetailPage
        stationId={station.id}
        onBack={onBack}
        api={new MockStationApi([station], 0)}
        chargePointApi={new MockChargePointApi([], 0)}
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
        chargePointApi={new MockChargePointApi([], 0)}
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

  it('reloads the charge-point list after creating a charge point', async () => {
    const user = userEvent.setup()
    const chargePointApi = new MockChargePointApi([], 0)
    const listChargePoints = vi.spyOn(chargePointApi, 'listChargePoints')
    render(
      <StationDetailPage
        stationId={station.id}
        onBack={() => undefined}
        api={new MockStationApi([station], 0)}
        chargePointApi={chargePointApi}
        canManageChargePoints
      />,
    )

    await screen.findByRole('heading', { name: station.name })
    await user.type(screen.getByRole('textbox', { name: 'Mã trụ' }), 'CP-Q1-002')
    await user.tab()
    expect(await screen.findByText('Mã trụ có thể sử dụng.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Thêm trụ sạc' }))

    expect(await screen.findByText('CP-Q1-002')).toBeInTheDocument()
    expect(await screen.findByText('Đã thêm trụ sạc')).toBeInTheDocument()
    await waitFor(() => expect(listChargePoints).toHaveBeenCalledTimes(2))
  })
})
