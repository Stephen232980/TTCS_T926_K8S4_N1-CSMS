import type {
  ChargePoint,
  ChargePointInput,
  ChargePointUpdate,
} from '../model/chargePoint'
import { ChargePointApiError, type ChargePointApi } from './chargePointApi'

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

export class MockChargePointApi implements ChargePointApi {
  private chargePoints: ChargePoint[]
  private readonly latency: number

  constructor(chargePoints: ChargePoint[] = [], latency = 300) {
    this.chargePoints = chargePoints.map((item) => ({
      ...item,
      connectors: item.connectors.map((connector) => ({ ...connector })),
    }))
    this.latency = latency
  }

  async checkCodeAvailability(code: string, signal?: AbortSignal) {
    await wait(this.latency, signal)
    const normalizedCode = code.trim()
    return {
      code: normalizedCode,
      available: !this.chargePoints.some((item) => item.code === normalizedCode),
    }
  }

  async createChargePoint(
    stationId: string,
    input: ChargePointInput,
  ): Promise<ChargePoint> {
    await wait(this.latency)
    const code = input.code.trim()

    if (this.chargePoints.some((item) => item.code === code)) {
      throw new ChargePointApiError(409, 'charge_point_code_already_exists')
    }

    const now = new Date().toISOString()
    const chargePoint: ChargePoint = {
      id: crypto.randomUUID(),
      stationId,
      code,
      name: null,
      status: 'offline',
      codeLockedAt: null,
      connectors: Array.from(
        { length: input.connectorCount },
        (_, index) => ({
          id: crypto.randomUUID(),
          connectorNumber: index + 1,
          status: 'unknown',
          createdAt: now,
          updatedAt: now,
        }),
      ),
      createdAt: now,
      updatedAt: now,
    }

    this.chargePoints = [...this.chargePoints, chargePoint]
    return {
      ...chargePoint,
      connectors: chargePoint.connectors.map((connector) => ({ ...connector })),
    }
  }

  async updateChargePoint(
    chargePointId: string,
    input: ChargePointUpdate,
  ): Promise<ChargePoint> {
    await wait(this.latency)
    const current = this.chargePoints.find((item) => item.id === chargePointId)
    if (!current) throw new ChargePointApiError(404, 'resource_not_found')
    if (current.codeLockedAt != null) {
      throw new ChargePointApiError(
        409,
        'charge_point_code_locked_after_charging',
      )
    }

    const code = input.code.trim()
    if (
      this.chargePoints.some(
        (item) =>
          item.id !== chargePointId &&
          item.code.toLowerCase() === code.toLowerCase(),
      )
    ) {
      throw new ChargePointApiError(409, 'charge_point_code_already_exists')
    }

    const updated = { ...current, code, updatedAt: new Date().toISOString() }
    this.chargePoints = this.chargePoints.map((item) =>
      item.id === chargePointId ? updated : item,
    )
    return {
      ...updated,
      connectors: updated.connectors.map((connector) => ({ ...connector })),
    }
  }
}
