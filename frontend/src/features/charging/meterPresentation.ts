export function meterLocationLabel(location: string): string {
  return ({ Outlet: 'Đầu nối', Inlet: 'Đầu vào', Body: 'Thân trụ', Cable: 'Cáp sạc', EV: 'Xe' } as Record<string, string>)[location] ?? location
}

export function meterUnitLabel(unit: string): string {
  return ({ Percent: '%', Hertz: 'Hz', Celsius: '°C', Celcius: '°C' } as Record<string, string>)[unit] ?? unit
}
