export interface BandValues {
  start: string
  end: string
  price: string
}
export interface BandSegment {
  start: number
  end: number
  rows: number[]
}
export const clockText = (minute: number) =>
  `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
export function clockMinute(value: string, end = false): number | null {
  if (end && value === '24:00') return 1440
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) return null
  return Number(value.slice(0, 2)) * 60 + Number(value.slice(3))
}
export function validateBands(bands: BandValues[]) {
  const errors = bands.map(() => [] as string[])
  const parts: { start: number; end: number; row: number }[] = []
  bands.forEach((band, row) => {
    const start = clockMinute(band.start),
      end = clockMinute(band.end, true)
    if (start === null || end === null || start === end)
      errors[row].push(
        'Nhập giờ HH:MM hợp lệ; giờ bắt đầu và kết thúc phải khác nhau.',
      )
    if (
      !/^\d+$/.test(band.price.trim()) ||
      band.price.trim().length > 100 ||
      BigInt(band.price.trim() || '0') > 9223372036854775807n
    )
      errors[row].push(
        'Đơn giá phải là số nguyên không âm trong giới hạn cho phép.',
      )
    if (start !== null && end !== null && start !== end) {
      if (start < end) parts.push({ start, end, row })
      else {
        parts.push({ start, end: 1440, row })
        if (end > 0) parts.push({ start: 0, end, row })
      }
    }
  })
  const points = [
    ...new Set([0, 1440, ...parts.flatMap((part) => [part.start, part.end])]),
  ].sort((a, b) => a - b)
  const segments: BandSegment[] = []
  points.slice(0, -1).forEach((start, i) => {
    const end = points[i + 1],
      rows = parts
        .filter((part) => part.start <= start && part.end >= end)
        .map((part) => part.row)
    segments.push({ start, end, rows })
    if (rows.length === 1) return
    const message = `${rows.length ? 'Khoảng chồng' : 'Khoảng hở'} ${clockText(start)}–${clockText(end)}`
    const related = rows.length
      ? rows
      : parts
          .filter((part) => part.end === start || part.start === end)
          .map((part) => part.row)
    for (const row of new Set(
      related.length ? related : bands.map((_, index) => index),
    ))
      errors[row].push(message)
  })
  return {
    errors,
    segments,
    valid:
      bands.length > 0 &&
      bands.length <= 1440 &&
      errors.every((row) => row.length === 0),
  }
}
export function normalizedBands(bands: BandValues[]) {
  return bands
    .flatMap((band) => {
      const start = clockMinute(band.start)!,
        end = clockMinute(band.end, true)!
      const common = {
        energy_rate_vnd_per_kwh: BigInt(band.price).toString(),
        label: '',
      }
      return start < end
        ? [{ ...common, start_min: start, end_min: end }]
        : [
            { ...common, start_min: start, end_min: 1440 },
            ...(end > 0 ? [{ ...common, start_min: 0, end_min: end }] : []),
          ]
    })
    .sort((a, b) => a.start_min - b.start_min)
}
