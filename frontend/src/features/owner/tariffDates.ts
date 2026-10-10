
export function stationToday(
  timeZone: string,
  now: Date = new Date(),
): string {
  if (!timeZone) {
    throw new Error('Chưa có múi giờ của trạm.')
  }

  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)

  const part = (type: string) =>
    parts.find((item) => item.type === type)?.value

  const year = part('year')
  const month = part('month')
  const day = part('day')

  if (!year || !month || !day) {
    throw new Error('Không xác định được ngày địa phương của trạm.')
  }

  return `${year}-${month}-${day}`
}

export function stationTomorrow(
  timeZone: string,
  now: Date = new Date(),
): string {
  const today = stationToday(timeZone, now)
  const [year, month, day] = today.split('-').map(Number)

  // Chỉ dùng UTC để cộng một ngày lịch sau khi đã
  // xác định đúng ngày địa phương của trạm.
  const nextDate = new Date(Date.UTC(year, month - 1, day + 1))

  return nextDate.toISOString().slice(0, 10)
}
