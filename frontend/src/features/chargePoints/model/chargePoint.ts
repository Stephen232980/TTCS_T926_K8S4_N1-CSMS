export interface Connector {
  connectorType?: string | null
  currentType?: 'AC' | 'DC' | null
  maxPowerKw?: string | null
  voltage?: string | null
  amperage?: string | null
  id: string
  connectorNumber: number
  status: string
  createdAt: string
  updatedAt: string
}

export interface ChargePoint {
  vendor?: string | null
  model?: string | null
  firmwareVersion?: string | null
  id: string
  stationId: string
  code: string
  name: string | null
  status: string
  codeLockedAt?: string | null
  connectors: Connector[]
  createdAt: string
  updatedAt: string
}

export interface ChargePointCodeAvailability {
  code: string
  available: boolean
}

export interface ChargePointInput {
  name?: string | null
  connectors?: ConnectorConfiguration[]
  code: string
  connectorCount: number
}

export interface ChargePointUpdate {
  code?: string
  name?: string | null
  connectors?: ConnectorConfiguration[]
}

export interface ConnectorConfiguration {
  connector_number: number
  connector_type?: string | null
  current_type?: 'AC' | 'DC' | null
  max_power_kw?: string | null
  voltage?: string | null
  amperage?: string | null
}

export interface ChargePointPage {
  items: ChargePoint[]
  page: number
  pageSize: number
  total: number
  totalPages: number
}
