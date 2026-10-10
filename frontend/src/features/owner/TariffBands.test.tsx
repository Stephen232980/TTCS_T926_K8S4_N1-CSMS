import {
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { TariffForm } from './TariffForm'
import { StationTariff } from './StationTariff'
import { createStationTariff } from './tariffApi'
import { validateBands, normalizedBands } from './tariffBands'
import { OwnerApiError } from './ownerApi'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
const change = (name: string, value: string) =>
  fireEvent.change(screen.getByLabelText(name), { target: { value } })
function setup(onSave = vi.fn(async () => {})) {
  render(
    <TariffForm
      currentTariff={null}
      tariffToday="2026-10-10"
      stationTimezone="Asia/Ho_Chi_Minh"
      onSave={onSave}
    />,
  )
  change('Cách tính giá điện', 'bands')
  change('Phí chiếm trụ mỗi phút (VNĐ)', '500')
  change('Thời gian ân hạn (phút)', '5')
  return onSave
}
function overnight() {
  change('Từ giờ khung 1', '22:00')
  change('Đến giờ khung 1', '02:00')
  change('Đơn giá khung 1', '3000')
  fireEvent.click(screen.getByRole('button', { name: 'Thêm khung giờ' }))
  change('Từ giờ khung 2', '02:00')
  change('Đến giờ khung 2', '22:00')
  change('Đơn giá khung 2', '4000')
}
const valid = [
  { start: '22:00', end: '02:00', price: '3000' },
  { start: '02:00', end: '22:00', price: '4000' },
]
it('reports gaps on adjacent rows before submit and disables saving', () => {
  const save = setup()
  overnight()
  change('Từ giờ khung 2', '03:00')
  expect(screen.getAllByText(/Khoảng hở 02:00–03:00/)).toHaveLength(2)
  expect(screen.getByRole('button', { name: 'Lưu biểu giá' })).toBeDisabled()
  expect(save).not.toHaveBeenCalled()
})
it('reports overlaps on both source rows and clears when corrected', () => {
  setup()
  overnight()
  change('Từ giờ khung 2', '01:00')
  expect(screen.getAllByText(/Khoảng chồng 01:00–02:00/)).toHaveLength(2)
  change('Từ giờ khung 2', '02:00')
  expect(screen.queryByText(/Khoảng chồng/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Lưu biểu giá' })).toBeEnabled()
})
it('supports deleting all rows and rejects empty coverage', () => {
  setup()
  fireEvent.click(screen.getByRole('button', { name: 'Xoá khung 1' }))
  expect(screen.getByText(/Thêm ít nhất một khung/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Lưu biểu giá' })).toBeDisabled()
})
it('validates boundaries, zero prices and exact BIGINT values', () => {
  for (const [start, end] of [
    ['24:00', '00:00'],
    ['00:00', '00:00'],
    ['12:60', '24:00'],
  ])
    expect(validateBands([{ start, end, price: '0' }]).valid).toBe(false)
  expect(
    validateBands([{ start: '00:00', end: '24:00', price: '0' }]).valid,
  ).toBe(true)
  expect(
    validateBands([
      { start: '00:00', end: '24:00', price: '9223372036854775808' },
    ]).valid,
  ).toBe(false)
  expect(normalizedBands(valid).map((b) => [b.start_min, b.end_min])).toEqual([
    [0, 120],
    [120, 1320],
    [1320, 1440],
  ])
})
it('serializes bands without a flat rate and without rounding 64-bit money', async () => {
  const fetcher = vi.fn(
    async () => new Response(JSON.stringify({ id: 'saved' }), { status: 201 }),
  )
  vi.stubGlobal('fetch', fetcher)
  await createStationTariff('station-id', {
    effectiveFrom: '2026-10-10',
    pricePerKwh: '',
    idleFeePerMinute: '0',
    graceMinutes: '0',
    bands: [{ start: '00:00', end: '24:00', price: '9223372036854775807' }],
  })
  const options = (fetcher.mock.calls[0] as unknown as [string, RequestInit])[1]
  expect(options.body).toContain(
    '"energy_rate_vnd_per_kwh":9223372036854775807',
  )
  expect(
    String(options.body).startsWith('{"effective_from":"2026-10-10","bands":'),
  ).toBe(true)
})
it('maps structured API row errors and preserves inputs for correction', async () => {
  const save = vi.fn(async () => {
    throw new OwnerApiError(422, [
      { loc: ['body', 'bands'], input_indices: [1], msg: 'Lỗi khung từ API' },
    ])
  })
  setup(save)
  overnight()
  fireEvent.click(screen.getByRole('button', { name: 'Lưu biểu giá' }))
  await screen.findByText('Lỗi khung từ API')
  expect(screen.getByLabelText('Từ giờ khung 2')).toHaveValue('02:00')
  change('Đơn giá khung 2', '4100')
  expect(screen.queryByText('Lỗi khung từ API')).not.toBeInTheDocument()
})
it('blocks double submit and disables band editing while saving', async () => {
  let finish!: () => void
  const save = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve
      }),
  )
  setup(save)
  overnight()
  const button = screen.getByRole('button', { name: 'Lưu biểu giá' })
  fireEvent.click(button)
  fireEvent.click(button)
  expect(save).toHaveBeenCalledTimes(1)
  expect(screen.getByLabelText('Từ giờ khung 1')).toBeDisabled()
  finish()
  await waitFor(() =>
    expect(screen.getByLabelText('Từ giờ khung 1')).toBeEnabled(),
  )
})
it('reloads normalized overnight bands after saving and reopening station detail', async () => {
  let saved = false
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      const payload = JSON.parse(String(options.body))
      expect(payload.bands[0].start_min).toBe(1320)
      expect(payload.bands[0].end_min).toBe(120)
      expect(payload.energy_rate_vnd_per_kwh).toBeUndefined()
      saved = true
      return new Response(JSON.stringify({ id: 'saved' }), { status: 201 })
    }
    return new Response(
      JSON.stringify({
        today: '2026-10-10',
        timezone: 'Asia/Ho_Chi_Minh',
        has_versions: saved,
        current: saved
          ? {
              effective_from: '2026-10-10',
              idle_rate_vnd_per_minute: '500',
              grace_minutes: 5,
              bands: normalizedBands(valid),
            }
          : null,
        upcoming: null,
      }),
    )
  })
  vi.stubGlobal('fetch', fetcher)
  const view = render(<StationTariff stationId="station-id" />)
  await screen.findByLabelText('Cách tính giá điện')
  change('Cách tính giá điện', 'bands')
  change('Phí chiếm trụ mỗi phút (VNĐ)', '500')
  change('Thời gian ân hạn (phút)', '5')
  overnight()
  fireEvent.click(screen.getByRole('button', { name: 'Lưu biểu giá' }))
  await screen.findByText(/22:00–24:00: 3.000/)
  view.unmount()
  render(<StationTariff stationId="station-id" />)
  await screen.findByText(/00:00–02:00: 3.000/)
  expect(screen.getByText(/22:00–24:00: 3.000/)).toBeInTheDocument()
})
