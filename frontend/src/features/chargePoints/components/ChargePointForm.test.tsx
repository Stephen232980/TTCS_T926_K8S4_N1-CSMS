import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChargePointApiError, type ChargePointApi } from '../api/chargePointApi'
import { MockChargePointApi } from '../api/mockChargePointApi'
import type { ChargePoint } from '../model/chargePoint'
import { ChargePointForm } from './ChargePointForm'

async function enterAvailableCode(
  user: ReturnType<typeof userEvent.setup>,
  code = 'CP-Q1-001',
) {
  const codeInput = screen.getByLabelText('Mã trụ')
  await user.type(codeInput, code)
  await user.tab()
  expect(await screen.findByText('Mã trụ có thể sử dụng.')).toBeInTheDocument()
}

describe('ChargePointForm', () => {
  it('checks code availability once when the code field loses focus', async () => {
    const user = userEvent.setup()
    const api = new MockChargePointApi([], 0)
    const checkCodeAvailability = vi.spyOn(api, 'checkCodeAvailability')
    render(
      <ChargePointForm
        stationId="station-1"
        api={api}
        onCreated={() => undefined}
      />,
    )

    await enterAvailableCode(user)

    expect(checkCodeAvailability).toHaveBeenCalledOnce()
    expect(checkCodeAvailability).toHaveBeenCalledWith(
      'CP-Q1-001',
      expect.any(AbortSignal),
    )
  })

  it('marks an existing code invalid before submit', async () => {
    const user = userEvent.setup()
    const api = new MockChargePointApi([], 0)
    await api.createChargePoint('station-2', {
      code: 'CP-EXISTING-001',
      connectorCount: 1,
    })
    const createChargePoint = vi.spyOn(api, 'createChargePoint')
    render(
      <ChargePointForm
        stationId="station-1"
        api={api}
        onCreated={() => undefined}
      />,
    )

    const codeInput = screen.getByLabelText('Mã trụ')
    await user.type(codeInput, 'CP-EXISTING-001')
    await user.tab()

    expect(await screen.findByText('Mã trụ đã được sử dụng.')).toBeInTheDocument()
    expect(codeInput).toHaveAttribute('aria-invalid', 'true')
    await user.click(screen.getByRole('button', { name: 'Thêm trụ sạc' }))
    expect(createChargePoint).toHaveBeenCalledTimes(0)
  })

  it('creates a charge point with the selected connector count', async () => {
    const user = userEvent.setup()
    const api = new MockChargePointApi([], 0)
    const onCreated = vi.fn()
    render(
      <ChargePointForm stationId="station-1" api={api} onCreated={onCreated} />,
    )

    await enterAvailableCode(user)
    const connectorCount = screen.getByLabelText('Số đầu nối')
    await user.clear(connectorCount)
    await user.type(connectorCount, '4')
    await user.click(screen.getByRole('button', { name: 'Thêm trụ sạc' }))

    await waitFor(() => expect(onCreated).toHaveBeenCalledOnce())
    expect(onCreated.mock.calls[0][0]).toMatchObject({
      stationId: 'station-1',
      code: 'CP-Q1-001',
      connectors: [
        { connectorNumber: 1 },
        { connectorNumber: 2 },
        { connectorNumber: 3 },
        { connectorNumber: 4 },
      ],
    })
  })

  it('prevents duplicate submissions while create is pending', async () => {
    const user = userEvent.setup()
    const checkCodeAvailability = vi.fn().mockResolvedValue({
      code: 'CP-PENDING-001',
      available: true,
    })
    const createChargePoint = vi.fn(() => new Promise<ChargePoint>(() => undefined))
    const api: ChargePointApi = { checkCodeAvailability, createChargePoint }
    render(
      <ChargePointForm
        stationId="station-1"
        api={api}
        onCreated={() => undefined}
      />,
    )

    await enterAvailableCode(user, 'CP-PENDING-001')
    await user.dblClick(screen.getByRole('button', { name: 'Thêm trụ sạc' }))

    expect(createChargePoint).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: 'Đang thêm…' })).toBeDisabled()
  })

  it('maps a server duplicate response back to the code field', async () => {
    const user = userEvent.setup()
    const api = new MockChargePointApi([], 0)
    vi.spyOn(api, 'createChargePoint').mockRejectedValue(
      new ChargePointApiError(409, 'charge_point_code_already_exists'),
    )
    render(
      <ChargePointForm
        stationId="station-1"
        api={api}
        onCreated={() => undefined}
      />,
    )

    await enterAvailableCode(user, 'CP-RACE-001')
    await user.click(screen.getByRole('button', { name: 'Thêm trụ sạc' }))

    expect(await screen.findByText('Mã trụ đã được sử dụng.')).toBeInTheDocument()
    expect(screen.getByLabelText('Mã trụ')).toHaveValue('CP-RACE-001')
  })
})
