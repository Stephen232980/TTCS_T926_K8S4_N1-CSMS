import { describe, expect, it } from 'vitest'
import { ChargePointApiError } from './chargePointApi'
import { MockChargePointApi } from './mockChargePointApi'

describe('MockChargePointApi', () => {
  it('creates the requested number of unknown connectors', async () => {
    const api = new MockChargePointApi([], 0)

    const chargePoint = await api.createChargePoint('station-1', {
      code: '  CP-Q1-001  ',
      connectorCount: 4,
    })

    expect(chargePoint.code).toBe('CP-Q1-001')
    expect(chargePoint.connectors.map((item) => item.connectorNumber)).toEqual([
      1, 2, 3, 4,
    ])
    expect(chargePoint.connectors.every((item) => item.status === 'unknown')).toBe(
      true,
    )
    await expect(api.checkCodeAvailability('CP-Q1-001')).resolves.toEqual({
      code: 'CP-Q1-001',
      available: false,
    })
  })

  it('rejects a duplicate code on create', async () => {
    const api = new MockChargePointApi([], 0)
    const input = { code: 'CP-DUPLICATE-001', connectorCount: 2 }
    await api.createChargePoint('station-1', input)

    await expect(api.createChargePoint('station-2', input)).rejects.toEqual(
      expect.objectContaining<Partial<ChargePointApiError>>({
        status: 409,
        detail: 'charge_point_code_already_exists',
      }),
    )
  })
})
