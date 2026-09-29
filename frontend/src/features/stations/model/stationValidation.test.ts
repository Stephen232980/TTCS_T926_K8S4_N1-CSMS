import { describe, expect, it } from 'vitest'
import {
  validateStationForm,
  type StationFormValues,
} from './stationValidation'

const validValues: StationFormValues = {
  name: 'Trạm Quận 1',
  address: '123 Nguyễn Huệ, Quận 1, TP.HCM',
  latitude: '10.7731',
  longitude: '106.7032',
}

describe('validateStationForm', () => {
  it('trims text and parses valid coordinates', () => {
    const result = validateStationForm({
      ...validValues,
      name: '  Trạm Quận 1  ',
      address: '  123 Nguyễn Huệ, Quận 1, TP.HCM  ',
    })

    expect(result).toEqual({
      success: true,
      data: {
        name: 'Trạm Quận 1',
        address: '123 Nguyễn Huệ, Quận 1, TP.HCM',
        latitude: 10.7731,
        longitude: 106.7032,
      },
      errors: {},
    })
  })

  it('accepts coordinate boundary values', () => {
    expect(
      validateStationForm({
        ...validValues,
        latitude: '-90',
        longitude: '180',
      }).success,
    ).toBe(true)
  })

  it('returns required errors for empty fields', () => {
    const result = validateStationForm({
      name: '   ',
      address: '',
      latitude: ' ',
      longitude: '',
    })

    expect(result).toEqual({
      success: false,
      errors: {
        name: 'Tên trạm là bắt buộc',
        address: 'Địa chỉ là bắt buộc',
        latitude: 'Vĩ độ là bắt buộc',
        longitude: 'Kinh độ là bắt buộc',
      },
    })
  })

  it('rejects text exceeding the contract limits', () => {
    const result = validateStationForm({
      ...validValues,
      name: 'a'.repeat(151),
      address: 'b'.repeat(501),
    })

    expect(result).toMatchObject({
      success: false,
      errors: {
        name: 'Tên trạm không được vượt quá 150 ký tự',
        address: 'Địa chỉ không được vượt quá 500 ký tự',
      },
    })
  })

  it('rejects coordinates outside their valid ranges', () => {
    const result = validateStationForm({
      ...validValues,
      latitude: '90.01',
      longitude: '-180.01',
    })

    expect(result).toMatchObject({
      success: false,
      errors: {
        latitude: 'Vĩ độ phải nằm trong khoảng -90 đến 90',
        longitude: 'Kinh độ phải nằm trong khoảng -180 đến 180',
      },
    })
  })

  it('rejects non-numeric coordinates', () => {
    const result = validateStationForm({
      ...validValues,
      latitude: 'mười',
      longitude: '106.7 độ',
    })

    expect(result).toMatchObject({
      success: false,
      errors: {
        latitude: 'Vĩ độ phải là một số hợp lệ',
        longitude: 'Kinh độ phải là một số hợp lệ',
      },
    })
  })
})
