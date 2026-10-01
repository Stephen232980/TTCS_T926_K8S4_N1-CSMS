export interface Connector {
  id: string
  connectorNumber: number
  status: string
  createdAt: string
  updatedAt: string
}

export interface ChargePoint {
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
  code: string
  connectorCount: number
}

export interface ChargePointUpdate {
  code: string
}
