import { describe, expect, it, vi } from 'vitest'
import { SESSION_UNAUTHORIZED_EVENT } from '../../auth/sessionEvents'
import { ChargePointApiError } from './chargePointApi'
import { HttpChargePointApi } from './httpChargePointApi'

const chargePointResponse = {
  id: 'charge-point-1',
  station_id: 'station-1',
  code: 'CP-Q1-001',
  name: null,
  status: 'offline',
  connectors: [
    {
      id: 'connector-1',
      connector_number: 1,
      status: 'unknown',
      created_at: '2026-09-30T10:00:00Z',
      updated_at: '2026-09-30T10:00:00Z',
    },
  ],
  created_at: '2026-09-30T10:00:00Z',
  updated_at: '2026-09-30T10:00:00Z',
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('HttpChargePointApi', () => {
  it('checks a trimmed code with cookie credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ code: 'CP-Q1-001', available: true }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const api = new HttpChargePointApi('http://localhost:8001/')

    const result = await api.checkCodeAvailability(
      '  CP-Q1-001  ',
      controller.signal,
    )

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/v1/charge-points/code-availability?code=CP-Q1-001',
      { credentials: 'include', signal: controller.signal },
    )
    expect(result).toEqual({ code: 'CP-Q1-001', available: true })
  })

  it('creates a charge point and maps connectors', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(chargePointResponse, 201))
    vi.stubGlobal('fetch', fetchMock)
    const api = new HttpChargePointApi()

    const result = await api.createChargePoint('station/1', {
      code: 'CP-Q1-001',
      connectorCount: 1,
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/stations/station%2F1/charge-points',
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: 'CP-Q1-001', connector_count: 1 }),
      },
    )
    expect(result).toMatchObject({
      stationId: 'station-1',
      code: 'CP-Q1-001',
      connectors: [{ connectorNumber: 1, status: 'unknown' }],
    })
  })

  it('exposes duplicate-code error details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: 'charge_point_code_already_exists' }, 409),
      ),
    )
    const api = new HttpChargePointApi()

    await expect(
      api.createChargePoint('station-1', {
        code: 'CP-Q1-001',
        connectorCount: 2,
      }),
    ).rejects.toEqual(
      expect.objectContaining<Partial<ChargePointApiError>>({
        status: 409,
        detail: 'charge_point_code_already_exists',
      }),
    )
  })

  it('notifies the app when the session is unauthorized', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'Chưa đăng nhập' }, 401)),
    )
    const listener = vi.fn()
    window.addEventListener(SESSION_UNAUTHORIZED_EVENT, listener)

    await expect(
      new HttpChargePointApi().checkCodeAvailability('CP-Q1-001'),
    ).rejects.toEqual(expect.objectContaining({ status: 401 }))

    expect(listener).toHaveBeenCalledTimes(1)
    window.removeEventListener(SESSION_UNAUTHORIZED_EVENT, listener)
  })
})
