import type { StationInput } from './station'

export interface StationFormValues {
  name: string
  address: string
  latitude: string
  longitude: string
}

export type StationFormField = keyof StationFormValues
export type StationFormErrors = Partial<Record<StationFormField, string>>

export type StationValidationResult =
  | {
      success: true
      data: StationInput
      errors: Record<string, never>
    }
  | {
      success: false
      errors: StationFormErrors
    }

type CoordinateResult =
  | { success: true; value: number }
  | { success: false; error: string }

function validateCoordinate(
  rawValue: string,
  label: string,
  minimum: number,
  maximum: number,
): CoordinateResult {
  const valueText = rawValue.trim()

  if (valueText.length === 0) {
    return { success: false, error: `${label} là bắt buộc` }
  }

  const value = Number(valueText)

  if (!Number.isFinite(value)) {
    return { success: false, error: `${label} phải là một số hợp lệ` }
  }

  if (value < minimum || value > maximum) {
    return {
      success: false,
      error: `${label} phải nằm trong khoảng ${minimum} đến ${maximum}`,
    }
  }

  return { success: true, value }
}

export function validateStationForm(
  values: StationFormValues,
): StationValidationResult {
  const errors: StationFormErrors = {}
  const name = values.name.trim()
  const address = values.address.trim()

  if (name.length === 0) {
    errors.name = 'Tên trạm là bắt buộc'
  } else if (name.length > 150) {
    errors.name = 'Tên trạm không được vượt quá 150 ký tự'
  }

  if (address.length === 0) {
    errors.address = 'Địa chỉ là bắt buộc'
  } else if (address.length > 500) {
    errors.address = 'Địa chỉ không được vượt quá 500 ký tự'
  }

  const latitude = validateCoordinate(values.latitude, 'Vĩ độ', -90, 90)
  const longitude = validateCoordinate(values.longitude, 'Kinh độ', -180, 180)

  if (!latitude.success) {
    errors.latitude = latitude.error
  }

  if (!longitude.success) {
    errors.longitude = longitude.error
  }

  if (
    Object.keys(errors).length > 0 ||
    !latitude.success ||
    !longitude.success
  ) {
    return { success: false, errors }
  }

  return {
    success: true,
    data: {
      name,
      address,
      latitude: latitude.value,
      longitude: longitude.value,
    },
    errors: {},
  }
}
