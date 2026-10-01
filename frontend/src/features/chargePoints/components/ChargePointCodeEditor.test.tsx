import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChargePointApiError } from '../api/chargePointApi'
import { MockChargePointApi } from '../api/mockChargePointApi'
import type { ChargePoint } from '../model/chargePoint'
import { ChargePointCodeEditor } from './ChargePointCodeEditor'

const chargePoint: ChargePoint = {
  id: 'charge-point-1',
  stationId: 'station-1',
  code: 'CP-OLD',
  name: null,
  status: 'offline',
  codeLockedAt: null,
  connectors: [],
  createdAt: '2026-09-30T10:00:00Z',
  updatedAt: '2026-09-30T10:00:00Z',
}

describe('ChargePointCodeEditor', () => {
  it('updates an unlocked charge-point code', async () => {
    const user = userEvent.setup()
    const api = new MockChargePointApi([chargePoint], 0)
    const onUpdated = vi.fn()
    render(
      <ChargePointCodeEditor
        chargePoint={chargePoint}
        api={api}
        onUpdated={onUpdated}
        onCancel={() => undefined}
      />,
    )

    const input = screen.getByLabelText('Mã trụ')
    await user.clear(input)
    await user.type(input, ' CP-NEW ')
    await user.click(screen.getByRole('button', { name: 'Lưu mã trụ' }))

    expect(onUpdated).toHaveBeenCalledWith(
      expect.objectContaining({ code: 'CP-NEW' }),
    )
  })

  it('explains a server-side code lock and preserves the input', async () => {
    const user = userEvent.setup()
    const api = new MockChargePointApi([chargePoint], 0)
    vi.spyOn(api, 'updateChargePoint').mockRejectedValue(
      new ChargePointApiError(
        409,
        'charge_point_code_locked_after_charging',
      ),
    )
    render(
      <ChargePointCodeEditor
        chargePoint={chargePoint}
        api={api}
        onUpdated={() => undefined}
        onCancel={() => undefined}
      />,
    )

    const input = screen.getByLabelText('Mã trụ')
    await user.clear(input)
    await user.type(input, 'CP-NEW')
    await user.click(screen.getByRole('button', { name: 'Lưu mã trụ' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Mã trụ đã được khóa sau phiên sạc đầu tiên và không thể thay đổi.',
    )
    expect(input).toHaveValue('CP-NEW')
  })

  it('disables editing when the lock is already known', () => {
    render(
      <ChargePointCodeEditor
        chargePoint={{ ...chargePoint, codeLockedAt: '2026-09-30T11:00:00Z' }}
        api={new MockChargePointApi()}
        onUpdated={() => undefined}
        onCancel={() => undefined}
      />,
    )

    expect(screen.getByLabelText('Mã trụ')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Lưu mã trụ' })).toBeDisabled()
    expect(screen.getByText('Mã đã khóa sau phiên sạc đầu tiên.')).toBeInTheDocument()
  })
})
