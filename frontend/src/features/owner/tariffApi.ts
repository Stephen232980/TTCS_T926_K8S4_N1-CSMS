import { ownerRequest } from './ownerApi'

export interface TariffCreateInput {
  effectiveFrom: string
  pricePerKwh: string
  idleFeePerMinute: string
  graceMinutes: string
}

export interface TariffCreated {
  id: string
  station_id: string
  effective_from: string
  created_at: string
}

export interface TariffDisplay {
  effective_from: string
  idle_rate_vnd_per_minute: string
  grace_minutes: number
  bands: {
    start_min: number
    end_min: number
    label: string
    energy_rate_vnd_per_kwh: string
  }[]
}
export interface TariffContext {
  today: string
  timezone: string
  has_versions: boolean
  current: TariffDisplay | null
  upcoming: TariffDisplay | null
}
export const readTariffContext = (stationId: string, signal?: AbortSignal) =>
  ownerRequest<TariffContext>(
    `/owner/stations/${encodeURIComponent(stationId)}/tariffs/context`,
    { signal },
  )

const MAX_MONEY = BigInt('9223372036854775807')
const MAX_GRACE = BigInt('2147483647')

function jsonInteger(raw: string, maximum: bigint, field: string): string {
  const value = raw.trim()

  if (!/^\d+$/.test(value)) {
    throw new Error(`${field} phải là số nguyên không âm.`)
  }

  const parsed = BigInt(value)

  if (parsed > maximum) {
    throw new Error(`${field} vượt giới hạn cho phép.`)
  }

  return parsed.toString()
}

export async function createStationTariff(
  stationId: string,
  input: TariffCreateInput,
): Promise<TariffCreated> {
  const effectiveFrom = input.effectiveFrom.trim()

  if (!/^\d{4}-\d{2}-\d{2}$/.test(effectiveFrom)) {
    throw new Error('Ngày hiệu lực phải có dạng YYYY-MM-DD.')
  }

  const price = jsonInteger(input.pricePerKwh, MAX_MONEY, 'Đơn giá điện')

  const idleFee = jsonInteger(
    input.idleFeePerMinute,
    MAX_MONEY,
    'Phí chiếm trụ',
  )

  const grace = jsonInteger(input.graceMinutes, MAX_GRACE, 'Thời gian ân hạn')

  // Gửi các số nguyên dưới dạng JSON number chính xác,
  // không chuyển qua Number() của JavaScript.
  const body = [
    '{"effective_from":',
    JSON.stringify(effectiveFrom),
    ',"energy_rate_vnd_per_kwh":',
    price,
    ',"idle_rate_vnd_per_minute":',
    idleFee,
    ',"grace_minutes":',
    grace,
    '}',
  ].join('')

  return ownerRequest<TariffCreated>(
    `/owner/stations/${encodeURIComponent(stationId)}/tariffs`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body,
    },
  )
}
