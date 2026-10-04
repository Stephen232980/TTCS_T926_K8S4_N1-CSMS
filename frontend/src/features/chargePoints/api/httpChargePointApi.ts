import type {
  ChargePoint,
  ChargePointCodeAvailability,
  ChargePointInput,
  ChargePointPage,
  ChargePointUpdate,
  Connector,
} from '../model/chargePoint'
import { ChargePointApiError, type ChargePointApi } from './chargePointApi'
import { notifySessionUnauthorized } from '../../auth/sessionEvents'

interface ConnectorResponse {
  connector_type?: string | null
  current_type?: 'AC' | 'DC' | null
  max_power_kw?: string | null
  voltage?: string | null
  amperage?: string | null
  id: string
  connector_number: number
  status: string
  created_at: string
  updated_at: string
}

interface ChargePointResponse {
  vendor?: string | null
  model?: string | null
  firmware_version?: string | null
  id: string
  station_id: string
  code: string
  name: string | null
  status: string
  code_locked_at: string | null
  connectors: ConnectorResponse[]
  created_at: string
  updated_at: string
}

interface CodeAvailabilityResponse {
  code: string
  available: boolean
}

interface ChargePointListResponse {
  items: ChargePointResponse[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

interface ErrorResponse {
  detail?: unknown
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
  throw new ChargePointApiError(response.status, detail)
}

function mapConnector(response: ConnectorResponse): Connector {
  return {
    id: response.id,
    connectorNumber: response.connector_number,
    status: response.status,
    createdAt: response.created_at,
    updatedAt: response.updated_at,
    connectorType: response.connector_type,
    currentType: response.current_type,
    maxPowerKw: response.max_power_kw,
    voltage: response.voltage,
    amperage: response.amperage,
  }
}

function mapChargePoint(response: ChargePointResponse): ChargePoint {
  return {
    id: response.id,
    stationId: response.station_id,
    code: response.code,
    name: response.name,
    status: response.status,
    codeLockedAt: response.code_locked_at,
    vendor: response.vendor,
    model: response.model,
    firmwareVersion: response.firmware_version,
    connectors: response.connectors.map(mapConnector),
    createdAt: response.created_at,
    updatedAt: response.updated_at,
  }
}

const configuredBaseUrl =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''

export class HttpChargePointApi implements ChargePointApi {
  private readonly baseUrl: string

  constructor(baseUrl = configuredBaseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, '')
  }

  async listChargePoints(
    stationId: string,
    page = 1,
    pageSize = 20,
    signal?: AbortSignal,
  ): Promise<ChargePointPage> {
    const searchParams = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    })
    const response = await fetch(
      `${this.baseUrl}/api/v1/stations/${encodeURIComponent(stationId)}/charge-points?${searchParams.toString()}`,
      { credentials: 'include', signal },
    )
    const payload = await parseResponse<ChargePointListResponse>(response)
    return {
      items: payload.items.map(mapChargePoint),
      page: payload.page,
      pageSize: payload.page_size,
      total: payload.total,
      totalPages: payload.total_pages,
    }
  }

  async checkCodeAvailability(
    code: string,
    signal?: AbortSignal,
  ): Promise<ChargePointCodeAvailability> {
    const searchParams = new URLSearchParams({ code: code.trim() })
    const response = await fetch(
      `${this.baseUrl}/api/v1/charge-points/code-availability?${searchParams.toString()}`,
      {
        credentials: 'include',
        signal,
      },
    )
    const payload = await parseResponse<CodeAvailabilityResponse>(response)

    return {
      code: payload.code,
      available: payload.available,
    }
  }

  async createChargePoint(
    stationId: string,
    input: ChargePointInput,
  ): Promise<ChargePoint> {
    const response = await fetch(
      `${this.baseUrl}/api/v1/stations/${encodeURIComponent(stationId)}/charge-points`,
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: input.code,
          connector_count: input.connectorCount,
          ...(input.name !== undefined ? { name: input.name } : {}),
          ...(input.connectors !== undefined
            ? { connectors: input.connectors }
            : {}),
        }),
      },
    )

    return mapChargePoint(await parseResponse<ChargePointResponse>(response))
  }

  async updateChargePoint(
    chargePointId: string,
    input: ChargePointUpdate,
  ): Promise<ChargePoint> {
    const response = await fetch(
      `${this.baseUrl}/api/v1/charge-points/${encodeURIComponent(chargePointId)}`,
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...input,
          ...(input.code !== undefined ? { code: input.code.trim() } : {}),
        }),
      },
    )

    return mapChargePoint(await parseResponse<ChargePointResponse>(response))
  }
}
