import type {
  ChargePoint,
  ChargePointCodeAvailability,
  ChargePointInput,
  ChargePointUpdate,
  Connector,
} from '../model/chargePoint'
import { ChargePointApiError, type ChargePointApi } from './chargePointApi'
import { notifySessionUnauthorized } from '../../auth/sessionEvents'

interface ConnectorResponse {
  id: string
  connector_number: number
  status: string
  created_at: string
  updated_at: string
}

interface ChargePointResponse {
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
    connectors: response.connectors.map(mapConnector),
    createdAt: response.created_at,
    updatedAt: response.updated_at,
  }
}

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''

export class HttpChargePointApi implements ChargePointApi {
  private readonly baseUrl: string

  constructor(baseUrl = configuredBaseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, '')
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
        body: JSON.stringify({ code: input.code.trim() }),
      },
    )

    return mapChargePoint(await parseResponse<ChargePointResponse>(response))
  }
}
