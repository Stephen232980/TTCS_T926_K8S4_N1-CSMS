import { describe, expect, it } from 'vitest'
import type { Station, StationListQuery } from '../model/station'
import { MockStationApi } from './mockStationApi'

const stations: Station[] = [
  {
    id: 'station-1',
    name: 'Trạm Quận 1',
    address: '123 Nguyễn Huệ, Quận 1, TP.HCM',
    latitude: 10.7731,
    longitude: 106.7032,
    status: 'active',
    createdAt: '2026-09-20T08:30:00Z',
    updatedAt: '2026-09-20T08:30:00Z',
  },
  {
    id: 'station-2',
    name: 'Trạm Thủ Đức',
    address: '45 Võ Văn Ngân, Thủ Đức, TP.HCM',
    latitude: 10.8506,
    longitude: 106.7719,
    status: 'inactive',
    createdAt: '2026-09-21T09:00:00Z',
    updatedAt: '2026-09-21T09:00:00Z',
  },
  {
    id: 'station-3',
    name: 'Trạm Bình Thạnh',
    address: '18 Điện Biên Phủ, Bình Thạnh, TP.HCM',
    latitude: 10.8012,
    longitude: 106.7101,
    status: 'active',
    createdAt: '2026-09-22T10:15:00Z',
    updatedAt: '2026-09-22T10:15:00Z',
  },
]

const firstPage: StationListQuery = {
  page: 1,
  pageSize: 20,
}

describe('MockStationApi', () => {
  it('filters by search text and status', async () => {
    const api = new MockStationApi(stations, 0)

    const result = await api.listStations({
      ...firstPage,
      search: 'bình thạnh',
      status: 'active',
    })

    expect(result.items.map((station) => station.id)).toEqual(['station-3'])
    expect(result.total).toBe(1)
    expect(result.totalPages).toBe(1)
  })

  it('returns the requested page', async () => {
    const api = new MockStationApi(stations, 0)

    const result = await api.listStations({ page: 2, pageSize: 2 })

    expect(result.items.map((station) => station.id)).toEqual(['station-3'])
    expect(result).toMatchObject({
      page: 2,
      pageSize: 2,
      total: 3,
      totalPages: 2,
    })
  })

  it('creates an inactive station and adds it to the list', async () => {
    const api = new MockStationApi(stations, 0)

    const created = await api.createStation({
      name: 'Trạm Phú Nhuận',
      address: '10 Phan Đăng Lưu, Phú Nhuận, TP.HCM',
      latitude: 10.7992,
      longitude: 106.6802,
    })
    const result = await api.listStations(firstPage)

    expect(created).toMatchObject({
      name: 'Trạm Phú Nhuận',
      status: 'inactive',
    })
    expect(created.id).not.toBe('')
    expect(result.items[0]).toEqual(created)
    expect(result.total).toBe(4)
  })

  it('updates an existing station without changing untouched fields', async () => {
    const api = new MockStationApi(stations, 0)

    const updated = await api.updateStation('station-2', {
      name: 'Trạm Thủ Đức mới',
    })

    expect(updated).toMatchObject({
      id: 'station-2',
      name: 'Trạm Thủ Đức mới',
      address: stations[1].address,
      status: 'inactive',
    })
  })

  it('rejects an update for a missing station', async () => {
    const api = new MockStationApi(stations, 0)

    await expect(
      api.updateStation('missing-station', { name: 'Không tồn tại' }),
    ).rejects.toThrow('station_not_found')
  })

  it('aborts an in-flight list request', async () => {
    const api = new MockStationApi(stations, 50)
    const controller = new AbortController()

    const request = api.listStations(firstPage, controller.signal)
    controller.abort()

    await expect(request).rejects.toMatchObject({ name: 'AbortError' })
  })
})
