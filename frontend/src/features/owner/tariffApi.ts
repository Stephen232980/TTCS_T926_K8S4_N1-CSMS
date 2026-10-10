import { clockMinute, validateBands, type BandValues } from './tariffBands'
import { ownerRequest } from './ownerApi'

export interface TariffCreateInput {
  bands?: BandValues[]
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

async function saveStationTariff<T>(
  stationId: string,
  input: TariffCreateInput,
  tariffId?: string,
): Promise<T> {
  const effectiveFrom = input.effectiveFrom.trim()

  if (!/^\d{4}-\d{2}-\d{2}$/.test(effectiveFrom)) {
    throw new Error('Ngày hiệu lực phải có dạng YYYY-MM-DD.')
  }

  if (input.bands && !validateBands(input.bands).valid)
    throw new Error(
      'Các khung giờ phải hợp lệ, không chồng lấn và phủ kín 24 giờ.',
    )
  const pricePart = input.bands
    ? ',"bands":[' +
      input.bands
        .map(
          (band) =>
            '{"start_min":' +
            clockMinute(band.start) +
            ',"end_min":' +
            clockMinute(band.end, true) +
            ',"energy_rate_vnd_per_kwh":' +
            jsonInteger(band.price, MAX_MONEY, 'Đơn giá điện') +
            ',"label":' +
            JSON.stringify(band.label ?? '') +
            '}',
        )
        .join(',') +
      ']'
    : ',"energy_rate_vnd_per_kwh":' +
      jsonInteger(input.pricePerKwh, MAX_MONEY, 'Đơn giá điện')

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
    pricePart,
    ',"idle_rate_vnd_per_minute":',
    idleFee,
    ',"grace_minutes":',
    grace,
    '}',
  ].join('')

  return ownerRequest<T>(
    `/owner/stations/${encodeURIComponent(stationId)}/tariffs${tariffId ? '/' + encodeURIComponent(tariffId) : ''}`,
    {
      method: tariffId ? 'PATCH' : 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body,
    },
  )
}

export const createStationTariff = (
  stationId: string,
  input: TariffCreateInput,
) => saveStationTariff<TariffCreated>(stationId, input)
export const updateStationTariff = (
  stationId: string,
  tariffId: string,
  input: TariffCreateInput,
) => saveStationTariff<TariffVersion>(stationId, input, tariffId)
export interface TariffVersion extends TariffDisplay {
  id: string
  created_at: string
  status: 'current' | 'upcoming' | 'historical'
  editable: boolean
}
export interface TariffHistory {
  today: string
  timezone: string
  items: TariffVersion[]
  page: number
  page_size: number
  total: number
}
export const readTariffHistory = (
  stationId: string,
  page: number,
  signal?: AbortSignal,
) =>
  ownerRequest<TariffHistory>(
    `/owner/stations/${encodeURIComponent(stationId)}/tariffs?page=${page}&page_size=20`,
    { signal },
  )
