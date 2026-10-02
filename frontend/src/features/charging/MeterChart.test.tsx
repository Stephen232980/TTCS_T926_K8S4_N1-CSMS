import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MeterChart } from './MeterChart'
import type { MeterReading } from './MeterChart'
const reading = (value: string, timestamp: string, extra: Partial<MeterReading> = {}): MeterReading => ({ value, timestamp, measurand: 'Energy.Active.Import.Register', unit: 'Wh', phase: '', location: 'Outlet', ...extra })
const first = '2026-10-02T01:00:00Z'
const second = '2026-10-02T01:00:10Z'
const third = '2026-10-02T01:00:30Z'

describe('MeterChart', () => {
  it('sorts charger timestamps, converts Wh and marks an energy regression without hiding it', async () => {
    const { container } = render(<MeterChart sessionId={1} readings={[reading('1800', third), reading('1000', first), reading('2000', second)]} />)
    expect(screen.getByRole('img', { name: /3 số đo.*có số đo giảm/ })).toBeInTheDocument()
    expect(screen.getByText('1,8 kWh')).toBeInTheDocument()
    expect(container.querySelectorAll('.charging-chart-line--warning')).toHaveLength(1)
    fireEvent.change(screen.getByRole('slider'), { target: { value: '0' } })
    expect(screen.getByText('1 kWh')).toBeInTheDocument()
    expect(screen.queryByText('Số đo giảm')).not.toBeInTheDocument()
  })
  it('separates phases and switches between voltage and current with their own units', async () => {
    const user = userEvent.setup()
    render(<MeterChart sessionId={2} readings={[
      reading('230', first, { measurand: 'Voltage', unit: 'V', phase: 'L1' }),
      reading('228', second, { measurand: 'Voltage', unit: 'V', phase: 'L1' }),
      reading('240', first, { measurand: 'Voltage', unit: 'V', phase: 'L2' }),
      reading('32', first, { measurand: 'Current.Import', unit: 'A' }),
    ]} />)
    expect(screen.getByRole('img', { name: /điện áp phiên 2, 2 số đo/ })).toBeInTheDocument()
    expect(screen.queryByText('Số đo giảm')).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Nguồn số đo'), 'L2|Outlet')
    expect(screen.getByText('240 V')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Thông số'), 'Current.Import')
    expect(screen.getByText('32 A')).toBeInTheDocument()
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  })
  it('has no invented line when only one sample exists and ignores unsupported/nonfinite values', () => {
    const { container } = render(<MeterChart sessionId={3} readings={[reading('NaN', first), reading('9000', second, { unit: 'A' }), reading('2000', third)]} />)
    expect(screen.getByRole('img', { name: /1 số đo/ })).toBeInTheDocument()
    expect(container.querySelectorAll('.charging-chart-line')).toHaveLength(0)
    expect(screen.getByText('2 kWh')).toBeInTheDocument()
  })
  it('shows a truthful empty state when no plottable telemetry arrived', () => {
    render(<MeterChart sessionId={4} readings={[]} />)
    expect(screen.getByText('Chưa có dữ liệu biểu đồ')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
  it('supports power, offered power, battery, temperature and frequency without mixing them', async () => {
    const user = userEvent.setup()
    render(<MeterChart sessionId={5} readings={[
      reading('7200', first, { measurand: 'Power.Active.Import', unit: 'W' }),
      reading('11', first, { measurand: 'Power.Offered', unit: 'kW' }),
      reading('80', first, { measurand: 'SoC', unit: 'Percent' }),
      reading('38', first, { measurand: 'Temperature', unit: 'Celsius' }),
      reading('50', first, { measurand: 'Frequency', unit: 'Hertz' }),
    ]} />)
    expect(screen.getByText('7,2 kW')).toBeInTheDocument()
    for (const [metric, value] of [['Power.Offered', '11 kW'], ['SoC', '80 %'], ['Temperature', '38 °C'], ['Frequency', '50 Hz']]) {
      await user.selectOptions(screen.getByLabelText('Thông số'), metric)
      expect(screen.getByText(value)).toBeInTheDocument()
    }
  })
})


it('can inspect distinct values with the same timestamp without snapping to the first', () => {
  render(<MeterChart sessionId={6} readings={[reading('1000', first), reading('2000', first), reading('3000', second)]} />)
  fireEvent.change(screen.getByRole('slider'), { target: { value: '1' } })
  expect(screen.getByText('2 kWh')).toBeInTheDocument()
  expect(screen.getByRole('slider')).toHaveValue('1')
})
