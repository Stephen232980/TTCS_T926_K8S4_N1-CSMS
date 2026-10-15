export interface PowerBandValues {
  start: string
  end: string
  power_kw: string
}

export interface PowerBandSegment {
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

export function validatePowerBands(bands: PowerBandValues[]) {
  const errors = bands.map(() => [] as string[])
  const parts: { start: number; end: number; row: number }[] = []

  bands.forEach((band, row) => {
    const start = clockMinute(band.start)
    const end = clockMinute(band.end, true)

    if (start === null || end === null || start === end) {
      errors[row].push(
        'Nhập giờ HH:MM hợp lệ; giờ bắt đầu và kết thúc phải khác nhau.',
      )
    }

    const kwNum = parseFloat(band.power_kw.trim())
    if (isNaN(kwNum) || kwNum <= 0) {
      errors[row].push('Công suất phải là số dương lớn hơn 0 (kW).')
    }

    if (start !== null && end !== null && start !== end) {
      if (start < end) {
        parts.push({ start, end, row })
      } else {
        parts.push({ start, end: 1440, row })
        if (end > 0) parts.push({ start: 0, end, row })
      }
    }
  })

  const points = [
    ...new Set([0, 1440, ...parts.flatMap((part) => [part.start, part.end])]),
  ].sort((a, b) => a - b)

  const segments: PowerBandSegment[] = []
  points.slice(0, -1).forEach((start, i) => {
    const end = points[i + 1]
    const rows = parts
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
    ;(related.length ? related : bands.map((_, index) => index)).forEach(
      (row) => {
        if (!errors[row].includes(message)) errors[row].push(message)
      },
    )
  })

  const valid =
    bands.length > 0 &&
    errors.every((item) => item.length === 0) &&
    segments.length > 0 &&
    segments.every((segment) => segment.rows.length === 1) &&
    segments[0].start === 0 &&
    segments[segments.length - 1].end === 1440

  return { errors, segments, valid }
}
