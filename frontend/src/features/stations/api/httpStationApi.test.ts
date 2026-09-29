import { describe, expect, it, vi } from 'vitest'
import { SESSION_UNAUTHORIZED_EVENT } from '../../auth/sessionEvents'
import { HttpStationApi, StationApiError } from './httpStationApi'

const stationResponse = {
  id: 'station-1',
  owner_id: 'owner-1',
  name: 'Trạm Quận 1',
  address: '123 Nguyễn Huệ, Quận 1',
  latitude: 10.7731,
  longitude: 106.7032,
  status: 'inactive',
  created_at: '2026-09-29T10:00:00Z',
  updated_at: '2026-09-29T10:00:00Z',
} as const

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('HttpStationApi', () => {
  it('gets a station through the encoded station path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stationResponse))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const api = new HttpStationApi('http://localhost:8001/')

    const station = await api.getStation('station/1', controller.signal)

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/v1/stations/station%2F1',
      { credentials: 'include', signal: controller.signal },
    )
    expect(station).toMatchObject({
      id: 'station-1',
      name: 'Trạm Quận 1',
    })
  })

  it('lists stations with filters, cookie credentials and response mapping', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [stationResponse],
        page: 2,
        page_size: 20,
        total: 21,
        total_pages: 2,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const api = new HttpStationApi('http://localhost:8001/')

    const result = await api.listStations(
      {
        page: 2,
        pageSize: 20,
        search: '  Quận 1  ',
        status: 'inactive',
      },
      controller.signal,
    )

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/v1/stations?page=2&page_size=20&search=Qu%E1%BA%ADn+1&status=inactive',
      { credentials: 'include', signal: controller.signal },
    )
    expect(result).toEqual({
      items: [
        {
          id: 'station-1',
          name: 'Trạm Quận 1',
          address: '123 Nguyễn Huệ, Quận 1',
          latitude: 10.7731,
          longitude: 106.7032,
          status: 'inactive',
          createdAt: '2026-09-29T10:00:00Z',
          updatedAt: '2026-09-29T10:00:00Z',
        },
      ],
      page: 2,
      pageSize: 20,
      total: 21,
      totalPages: 2,
    })
  })

  it('creates a station with an idempotency key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stationResponse, 201))
    vi.stubGlobal('fetch', fetchMock)
    const api = new HttpStationApi('', () => 'fixed-idempotency-key')
    const input = {
      name: 'Trạm Quận 1',
      address: '123 Nguyễn Huệ, Quận 1',
      latitude: 10.7731,
      longitude: 106.7032,
    }

    const station = await api.createStation(input)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/stations', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': 'fixed-idempotency-key',
      },
      body: JSON.stringify(input),
    })
    expect(station.status).toBe('inactive')
  })

  it('updates a station through the encoded station path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        ...stationResponse,
        name: 'Trạm đã sửa',
        updated_at: '2026-09-29T11:00:00Z',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const api = new HttpStationApi()

    const station = await api.updateStation('station/1', {
      name: 'Trạm đã sửa',
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/stations/station%2F1', {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Trạm đã sửa' }),
    })
    expect(station.name).toBe('Trạm đã sửa')
    expect(station.updatedAt).toBe('2026-09-29T11:00:00Z')
  })

  it('exposes the HTTP status and API detail on errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: 'permission_denied' }, 403),
      ),
    )
    const api = new HttpStationApi()

    await expect(
      api.updateStation('station-1', { name: 'Không được phép' }),
    ).rejects.toEqual(
      expect.objectContaining<Partial<StationApiError>>({
        status: 403,
        detail: 'permission_denied',
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

    await expect(new HttpStationApi().getStation('station-1')).rejects.toEqual(
      expect.objectContaining({ status: 401 }),
    )

    expect(listener).toHaveBeenCalledTimes(1)
    window.removeEventListener(SESSION_UNAUTHORIZED_EVENT, listener)
  })
})
