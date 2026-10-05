import type {
  PaginatedResult,
  Station,
  StationInput,
  StationListQuery,
  StationStatus,
  StationUpdate,
} from '../model/station'
import type { StationApi } from './stationApi'
import { notifySessionUnauthorized } from '../../auth/sessionEvents'

interface StationResponse {
  photo_url?: string | null
  id: string
  owner_id: string
  name: string
  address: string
  latitude: number
  longitude: number
  status: StationStatus
  created_at: string
  updated_at: string
}

interface StationListResponse {
  items: StationResponse[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

interface ErrorResponse {
  detail?: unknown
}

export class StationApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(`station_api_error_${status}`)
    this.name = 'StationApiError'
    this.status = status
    this.detail = detail
  }
}

function mapStation(response: StationResponse): Station {
  return {
    id: response.id,
    name: response.name,
    address: response.address,
    latitude: response.latitude,
    longitude: response.longitude,
    status: response.status,
    createdAt: response.created_at,
    updatedAt: response.updated_at,
    photoUrl: response.photo_url,
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T

  if (response.status === 401) notifySessionUnauthorized()

  let detail: unknown
  try {
    detail = ((await response.json()) as ErrorResponse).detail
  } catch {
    detail = undefined
  }
  throw new StationApiError(response.status, detail)
}

const configuredBaseUrl =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''

export class HttpStationApi implements StationApi {
  private readonly baseUrl: string
  private readonly area: '' | 'ops'
  private readonly idempotencyKeyFactory: () => string

  constructor(
    baseUrl = configuredBaseUrl,
    idempotencyKeyFactory: () => string = () => crypto.randomUUID(),
    area: '' | 'ops' = '',
  ) {
    this.baseUrl = baseUrl.replace(/\/$/, '')
    this.area = area
    this.idempotencyKeyFactory = idempotencyKeyFactory
  }

  async getStation(stationId: string, signal?: AbortSignal): Promise<Station> {
    const response = await fetch(
      `${this.baseUrl}/api/v1${this.area ? `/${this.area}` : ''}/stations/${encodeURIComponent(stationId)}`,
      {
        credentials: 'include',
        signal,
      },
    )

    return mapStation(await parseResponse<StationResponse>(response))
  }

  async listStations(
    query: StationListQuery,
    signal?: AbortSignal,
  ): Promise<PaginatedResult<Station>> {
    const searchParams = new URLSearchParams({
      page: String(query.page),
      page_size: String(query.pageSize),
    })
    const search = query.search?.trim()
    if (search) searchParams.set('search', search)
    if (query.status) searchParams.set('status', query.status)

    const response = await fetch(
      `${this.baseUrl}/api/v1${this.area ? `/${this.area}` : ''}/stations?${searchParams.toString()}`,
      {
        credentials: 'include',
        signal,
      },
    )
    const payload = await parseResponse<StationListResponse>(response)

    return {
      items: payload.items.map(mapStation),
      page: payload.page,
      pageSize: payload.page_size,
      total: payload.total,
      totalPages: payload.total_pages,
    }
  }

  async createStation(input: StationInput): Promise<Station> {
    const response = await fetch(`${this.baseUrl}/api/v1${this.area ? `/${this.area}` : ''}/stations`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': this.idempotencyKeyFactory(),
      },
      body: JSON.stringify(input),
    })

    return mapStation(await parseResponse<StationResponse>(response))
  }

  async updateStation(
    stationId: string,
    input: StationUpdate,
  ): Promise<Station> {
    const response = await fetch(
      `${this.baseUrl}/api/v1${this.area ? `/${this.area}` : ''}/stations/${encodeURIComponent(stationId)}`,
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      },
    )

    return mapStation(await parseResponse<StationResponse>(response))
  }
}
