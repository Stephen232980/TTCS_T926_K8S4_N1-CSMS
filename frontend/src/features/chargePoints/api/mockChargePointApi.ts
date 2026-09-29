import type {
  ChargePoint,
  ChargePointInput,
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
}
