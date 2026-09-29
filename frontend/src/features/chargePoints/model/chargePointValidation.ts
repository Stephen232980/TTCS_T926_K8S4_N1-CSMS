export function validateChargePointCode(code: string): string {
  const normalizedCode = code.trim()
  if (!normalizedCode) return 'Nhập mã trụ sạc.'
  if (normalizedCode.length > 64) return 'Mã trụ không được vượt quá 64 ký tự.'
  return ''
}

export function validateConnectorCount(value: string): string {
  if (!value.trim()) return 'Nhập số đầu nối.'
  if (!/^[1-4]$/.test(value.trim())) return 'Số đầu nối phải từ 1 đến 4.'
  return ''
}
