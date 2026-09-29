import type {
  PaginatedResult,
  Station,
  StationInput,
  StationListQuery,
  StationUpdate,
} from '../model/station'
import type { StationApi } from './stationApi'

const initialStations: Station[] = [
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

function wait(duration: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Request aborted', 'AbortError'))
      return
    }

    const handleAbort = () => {
      globalThis.clearTimeout(timer)
      reject(new DOMException('Request aborted', 'AbortError'))
    }

    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener('abort', handleAbort)
      resolve()
    }, duration)

    signal?.addEventListener('abort', handleAbort, { once: true })
  })
}

export class MockStationApi implements StationApi {
  private stations: Station[]
  private readonly latency: number

  constructor(stations: Station[] = initialStations, latency = 300) {
    this.stations = stations.map((station) => ({ ...station }))
    this.latency = latency
  }

  async getStation(stationId: string, signal?: AbortSignal): Promise<Station> {
    await wait(this.latency, signal)
    const station = this.stations.find((item) => item.id === stationId)

    if (station === undefined) {
      throw new Error('station_not_found')
    }

    return { ...station }
  }

  async listStations(
    query: StationListQuery,
    signal?: AbortSignal,
  ): Promise<PaginatedResult<Station>> {
    await wait(this.latency, signal)

    const search = query.search?.trim().toLocaleLowerCase('vi')
    const filteredStations = this.stations.filter((station) => {
      const matchesStatus =
        query.status === undefined || station.status === query.status
      const matchesSearch =
        search === undefined ||
        search.length === 0 ||
        station.name.toLocaleLowerCase('vi').includes(search) ||
        station.address.toLocaleLowerCase('vi').includes(search)

      return matchesStatus && matchesSearch
    })

    const start = (query.page - 1) * query.pageSize
    const items = filteredStations
      .slice(start, start + query.pageSize)
      .map((station) => ({ ...station }))

    return {
      items,
      page: query.page,
      pageSize: query.pageSize,
      total: filteredStations.length,
      totalPages: Math.ceil(filteredStations.length / query.pageSize),
    }
  }

  async createStation(input: StationInput): Promise<Station> {
    await wait(this.latency)

    const now = new Date().toISOString()
    const station: Station = {
      id: crypto.randomUUID(),
      ...input,
      status: 'inactive',
      createdAt: now,
      updatedAt: now,
    }

    this.stations = [station, ...this.stations]

    return { ...station }
  }

  async updateStation(
    stationId: string,
    input: StationUpdate,
  ): Promise<Station> {
    await wait(this.latency)

    const stationIndex = this.stations.findIndex(
      (station) => station.id === stationId,
    )

    if (stationIndex === -1) {
      throw new Error('station_not_found')
    }

    const updatedStation: Station = {
      ...this.stations[stationIndex],
      ...input,
      updatedAt: new Date().toISOString(),
    }

    this.stations[stationIndex] = updatedStation

    return { ...updatedStation }
  }
}
