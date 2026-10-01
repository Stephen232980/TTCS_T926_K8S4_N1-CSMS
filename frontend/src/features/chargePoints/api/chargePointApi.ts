import type {
  ChargePoint,
  ChargePointCodeAvailability,
  ChargePointInput,
  ChargePointPage,
  ChargePointUpdate,
} from '../model/chargePoint'

export class ChargePointApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(`charge_point_api_error_${status}`)
    this.name = 'ChargePointApiError'
    this.status = status
    this.detail = detail
  }
}

export interface ChargePointApi {
  listChargePoints(
    stationId: string,
    page?: number,
    pageSize?: number,
    signal?: AbortSignal,
  ): Promise<ChargePointPage>

  checkCodeAvailability(
    code: string,
    signal?: AbortSignal,
  ): Promise<ChargePointCodeAvailability>

  createChargePoint(
    stationId: string,
    input: ChargePointInput,
  ): Promise<ChargePoint>

  updateChargePoint(
    chargePointId: string,
    input: ChargePointUpdate,
  ): Promise<ChargePoint>
}
