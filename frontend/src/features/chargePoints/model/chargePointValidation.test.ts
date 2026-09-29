import { describe, expect, it } from 'vitest'
import {
  validateChargePointCode,
  validateConnectorCount,
} from './chargePointValidation'

describe('charge point validation', () => {
  it('requires a code no longer than 64 characters', () => {
    expect(validateChargePointCode(' ')).toBe('Nhập mã trụ sạc.')
    expect(validateChargePointCode('x'.repeat(65))).toBe(
      'Mã trụ không được vượt quá 64 ký tự.',
    )
    expect(validateChargePointCode(' CP-Q1-001 ')).toBe('')
  })

  it('accepts only integer connector counts from 1 to 4', () => {
    expect(validateConnectorCount('')).toBe('Nhập số đầu nối.')
    expect(validateConnectorCount('0')).toBe('Số đầu nối phải từ 1 đến 4.')
    expect(validateConnectorCount('5')).toBe('Số đầu nối phải từ 1 đến 4.')
    expect(validateConnectorCount('2.5')).toBe('Số đầu nối phải từ 1 đến 4.')
    expect(validateConnectorCount('4')).toBe('')
  })
})
