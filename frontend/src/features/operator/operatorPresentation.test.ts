import { describe, expect, it } from 'vitest'
import { durationText, reviewGuidance, needsSessionWarning } from './operatorPresentation'

describe('operational presentation', () => {
  it('keeps routine notes quiet without hiding billing or operational problems', () => {
    expect(needsSessionWarning(['occupation_missing_status_timestamp'], false)).toBe(false)
    expect(needsSessionWarning(['manual_closure'], true)).toBe(false)
    expect(needsSessionWarning(['occupation_missing_status_timestamp'], true)).toBe(true)
    expect(needsSessionWarning(['occupation_missing_status_timestamp', 'meter_regression'], false)).toBe(true)
    expect(needsSessionWarning(['invoice_missing_tariff'], true)).toBe(true)
    expect(needsSessionWarning(['offline_timeout'], false)).toBe(true)
  })
  it('shows multi-day sessions without a large minute count', () => {
    expect(durationText(5996)).toBe('4 ngày 3 giờ 56 phút')
    expect(durationText(60)).toBe('1 giờ')
    expect(durationText(0)).toBe('0 phút')
  })
  it('distinguishes an offline record from stopping the physical charge', () => {
    expect(reviewGuidance('offline_timeout')).toContain('không dừng sạc')
    expect(reviewGuidance('stop_meter_below_latest')).toContain('không tự sửa số đo')
    expect(reviewGuidance('new_reason')).toContain('kèm mã phiên')
  })
})
