
import { describe, expect, it } from 'vitest'
import { stationToday, stationTomorrow } from './tariffDates'

describe('Ngày hiệu lực theo múi giờ trạm', () => {
  const now = new Date('2026-10-08T17:30:00Z')

  it('lấy đúng ngày tại Việt Nam', () => {
    expect(stationToday('Asia/Ho_Chi_Minh', now))
      .toBe('2026-10-09')
  })

  it('lấy đúng ngày tại Los Angeles', () => {
    expect(stationToday('America/Los_Angeles', now))
      .toBe('2026-10-08')
  })

  it('tính ngày mai theo múi giờ trạm', () => {
    expect(stationTomorrow('Asia/Ho_Chi_Minh', now))
      .toBe('2026-10-10')
  })

  it('không tự dùng múi giờ mặc định nếu thiếu dữ liệu', () => {
    expect(() => stationToday('', now)).toThrow()
  })
})
