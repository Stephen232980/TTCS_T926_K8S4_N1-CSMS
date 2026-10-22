import type { PowerBandValues } from './powerScheduleBands'

export interface PowerScheduleBandDisplay {
  id?: string
  start_min: number
  end_min: number
  start_time: string
  end_time: string
  power_limit_w: number
  power_limit_kw: string
}

export interface PowerScheduleResponse {
  id: string
  station_id: string
  effective_from: string
  created_at: string
  updated_at: string
  bands: PowerScheduleBandDisplay[]
}

export interface CurrentPowerLimitResponse {
  station_id: string
  timezone: string
  local_time: string
  local_date: string
  power_limit_w: number | null
  power_limit_kw: string | null
}

export async function fetchPowerSchedule(
  stationId: string,
  effectiveDate?: string,
): Promise<PowerScheduleResponse | null> {
  const url = effectiveDate
    ? `/api/v1/owner/stations/${stationId}/power-schedule?effective_date=${effectiveDate}`
    : `/api/v1/owner/stations/${stationId}/power-schedule`
  const res = await fetch(url)
  if (res.status === 404) return null
  if (!res.ok) throw new Error('Không thể tải lịch công suất trạm')
  const data = await res.json()
  return data
}

export async function fetchCurrentPowerLimit(
  stationId: string,
): Promise<CurrentPowerLimitResponse> {
  const res = await fetch(`/api/v1/owner/stations/${stationId}/power-schedule/current`)
  if (!res.ok) throw new Error('Không thể tải hạn mức công suất hiện tại')
  return res.json()
}

export async function savePowerSchedule(
  stationId: string,
  effectiveFrom: string,
  bands: PowerBandValues[],
): Promise<PowerScheduleResponse> {
  const payload = {
    effective_from: effectiveFrom,
    bands: bands.map((b) => ({
      start_time: b.start,
      end_time: b.end,
      power_limit_kw: parseFloat(b.power_kw) || 0,
    })),
  }

  const res = await fetch(`/api/v1/owner/stations/${stationId}/power-schedule`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!res.ok) {
    const errorData = (await res.json().catch(() => ({}))) as {
      detail?: string | Array<{ message?: string }>
    }
    throw new Error(
      errorData.detail
        ? Array.isArray(errorData.detail)
          ? errorData.detail.map((d) => d.message ?? 'Unknown error').join('; ')
          : errorData.detail
        : 'Lưu lịch công suất thất bại',
    )
  }

  return res.json()
}
