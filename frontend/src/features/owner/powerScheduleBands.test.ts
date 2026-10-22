import { describe, expect, it } from 'vitest'
import {
  clockMinute,
  clockText,
  validatePowerBands,
  type PowerBandValues,
} from './powerScheduleBands'

describe('Kiểm tra chuyển đổi phút đồng hồ', () => {
  it('chuyển đổi đúng phút trong ngày', () => {
    expect(clockMinute('00:00')).toBe(0)
    expect(clockMinute('06:30')).toBe(390)
    expect(clockMinute('23:59')).toBe(1439)
    expect(clockMinute('24:00', true)).toBe(1440)
  })

  it('từ chối giờ không hợp lệ', () => {
    expect(clockMinute('25:00')).toBeNull()
    expect(clockMinute('12:60')).toBeNull()
    expect(clockMinute('abc')).toBeNull()
  })

  it('định dạng clockText đúng', () => {
    expect(clockText(0)).toBe('00:00')
    expect(clockText(390)).toBe('06:30')
    expect(clockText(1440)).toBe('24:00')
  })
})

describe('Validation khung giờ công suất trạm (S-45 / G2)', () => {
  it('hợp lệ khi phủ kín 24 giờ với 1 khung', () => {
    const bands: PowerBandValues[] = [
      { start: '00:00', end: '24:00', power_kw: '50' },
    ]
    const result = validatePowerBands(bands)
    expect(result.valid).toBe(true)
    expect(result.segments.length).toBe(1)
    expect(result.segments[0].start).toBe(0)
    expect(result.segments[0].end).toBe(1440)
  })

  it('hợp lệ khi phủ kín 24 giờ với nhiều khung', () => {
    const bands: PowerBandValues[] = [
      { start: '00:00', end: '06:00', power_kw: '30' },
      { start: '06:00', end: '18:00', power_kw: '50' },
      { start: '18:00', end: '24:00', power_kw: '25' },
    ]
    const result = validatePowerBands(bands)
    expect(result.valid).toBe(true)
  })

  it('phát hiện khoảng hở', () => {
    const bands: PowerBandValues[] = [
      { start: '00:00', end: '12:00', power_kw: '50' },
      { start: '14:00', end: '24:00', power_kw: '50' }, // Hở 12:00 - 14:00
    ]
    const result = validatePowerBands(bands)
    expect(result.valid).toBe(false)
    expect(result.errors.some((errs) => errs.some((e) => e.includes('Khoảng hở')))).toBe(true)
  })

  it('phát hiện khoảng chồng', () => {
    const bands: PowerBandValues[] = [
      { start: '00:00', end: '14:00', power_kw: '50' },
      { start: '12:00', end: '24:00', power_kw: '50' }, // Chồng 12:00 - 14:00
    ]
    const result = validatePowerBands(bands)
    expect(result.valid).toBe(false)
    expect(result.errors.some((errs) => errs.some((e) => e.includes('Khoảng chồng')))).toBe(true)
  })

  it('báo lỗi khi công suất âm hoặc bằng 0', () => {
    const bands: PowerBandValues[] = [
      { start: '00:00', end: '24:00', power_kw: '0' },
    ]
    const result = validatePowerBands(bands)
    expect(result.valid).toBe(false)
    expect(result.errors[0].some((e) => e.includes('lớn hơn 0'))).toBe(true)
  })
})
