import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChargePointApiError } from '../api/chargePointApi'
import { MockChargePointApi } from '../api/mockChargePointApi'
import type { ChargePoint } from '../model/chargePoint'
import { ChargePointList } from './ChargePointList'

const chargePoint: ChargePoint = {
  id: 'charge-point-1',
  stationId: 'station-1',
  code: 'CP-Q1-001',
  name: null,
  status: 'offline',
  codeLockedAt: null,
  connectors: [
    {
      id: 'connector-1',
      connectorNumber: 1,
      status: 'unknown',
      createdAt: '2026-09-30T10:00:00Z',
      updatedAt: '2026-09-30T10:00:00Z',
    },
  ],
  createdAt: '2026-09-30T10:00:00Z',
  updatedAt: '2026-09-30T10:00:00Z',
}

describe('ChargePointList', () => {
  it('renders existing charge points and connector state', async () => {
    render(
      <ChargePointList
        stationId="station-1"
        api={new MockChargePointApi([chargePoint], 0)}
      />,
    )

    expect(await screen.findByText('CP-Q1-001')).toBeInTheDocument()
    expect(screen.getByText('#1 · Chưa rõ')).toBeInTheDocument()
    expect(screen.getByText('Ngoại tuyến')).toBeInTheDocument()
  })

  it('shows a useful empty state', async () => {
    render(
      <ChargePointList stationId="station-1" api={new MockChargePointApi([], 0)} />,
    )

    expect(await screen.findByText('Trạm chưa có trụ sạc')).toBeInTheDocument()
    expect(screen.getByText('Trụ đầu tiên bạn thêm sẽ xuất hiện tại đây.')).toBeInTheDocument()
  })

  it('changes pages and returns to the first page', async () => {
    const user = userEvent.setup()
    const chargePoints = Array.from({ length: 11 }, (_, index) => ({
      ...chargePoint,
      id: `charge-point-${index + 1}`,
      code: `CP-Q1-${String(index + 1).padStart(3, '0')}`,
    }))
    render(
      <ChargePointList
        stationId="station-1"
        api={new MockChargePointApi(chargePoints, 0)}
      />,
    )

    expect(await screen.findByText('CP-Q1-001')).toBeInTheDocument()
    expect(screen.getByText('Trang 1 / 2 · 11 trụ')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Trang trụ tiếp theo' }))

    expect(await screen.findByText('CP-Q1-011')).toBeInTheDocument()
    expect(screen.queryByText('CP-Q1-001')).not.toBeInTheDocument()
    expect(screen.getByText('Trang 2 / 2 · 11 trụ')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Trang trụ trước' }))

    expect(await screen.findByText('CP-Q1-001')).toBeInTheDocument()
    expect(screen.queryByText('CP-Q1-011')).not.toBeInTheDocument()
  })

  it('shows an authorization error and retries', async () => {
    const user = userEvent.setup()
    const api = new MockChargePointApi([chargePoint], 0)
    const listChargePoints = vi
      .spyOn(api, 'listChargePoints')
      .mockRejectedValueOnce(new ChargePointApiError(403, 'permission_denied'))
      .mockResolvedValueOnce({
        items: [chargePoint],
        page: 1,
        pageSize: 10,
        total: 1,
        totalPages: 1,
      })

    render(<ChargePointList stationId="station-1" api={api} />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Bạn không có quyền xem các trụ của trạm này.',
    )
    await user.click(screen.getByRole('button', { name: 'Thử lại' }))

    expect(await screen.findByText('CP-Q1-001')).toBeInTheDocument()
    expect(listChargePoints).toHaveBeenCalledTimes(2)
  })

  it('updates an unlocked code from the list', async () => {
    const user = userEvent.setup()
    const api = new MockChargePointApi([chargePoint], 0)
    render(<ChargePointList stationId="station-1" api={api} />)

    await user.click(await screen.findByRole('button', { name: 'Sửa mã' }))
    const input = screen.getByLabelText('Mã trụ')
    await user.clear(input)
    await user.type(input, 'CP-Q1-002')
    await user.click(screen.getByRole('button', { name: 'Lưu mã trụ' }))

    expect(await screen.findByText('CP-Q1-002')).toBeInTheDocument()
  })
})
