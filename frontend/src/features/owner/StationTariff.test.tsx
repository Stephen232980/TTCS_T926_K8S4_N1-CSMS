import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { StationTariff } from './StationTariff'
import { TariffForm } from './TariffForm'
import { OwnerWorkspace } from './OwnerWorkspace'

afterEach(() => vi.unstubAllGlobals())

it('shows the saved tariff in the actual station detail page', async () => {
  const station = { id: 'station-id', name: 'Trạm thử T-62', timezone: 'Asia/Ho_Chi_Minh', address: 'Địa chỉ thử', latitude: 21, longitude: 105, status: 'active' as const, createdAt: '', updatedAt: '' }
  const page = { items: [station], page: 1, pageSize: 20, total: 1, totalPages: 1 }
  const stationApi = { listStations: vi.fn(async () => page), getStation: vi.fn(async () => station), createStation: vi.fn(async () => station), updateStation: vi.fn(async () => station) }
  const chargePointApi = { listChargePoints: vi.fn(async () => ({ ...page, items: [], total: 0 })), checkCodeAvailability: vi.fn(), createChargePoint: vi.fn(), updateChargePoint: vi.fn() }
  let saved = false
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === 'POST') { saved = true; return response({ id: 'saved' }, 201) }
    if (url.includes('/tariffs/context')) return response({ today, timezone: station.timezone, has_versions: saved, current: saved ? tariff(today) : null, upcoming: null })
    return response({ items: [], total_pages: 0 })
  })
  vi.stubGlobal('fetch', fetcher)
  render(<OwnerWorkspace currentUser={{ id: 'owner', email: 'owner@example.com', roles: ['station_owner'] }} onLogout={async () => {}} stationApi={stationApi} chargePointApi={chargePointApi} />)
  fireEvent.click(await screen.findByRole('button', { name: /Trạm thử T-62/ }))
  await screen.findByText('Trạm chưa có biểu giá đang áp dụng.')
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Lưu biểu giá' }))
  await screen.findByText('3.500 VNĐ/kWh')
  expect(fetcher.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(1)
})
const today = '2026-10-10'
const tariff = (date: string, price = '3500') => ({
  effective_from: date,
  idle_rate_vnd_per_minute: '500',
  grace_minutes: 5,
  bands: [
    {
      start_min: 0,
      end_min: 1440,
      label: 'Cả ngày',
      energy_rate_vnd_per_kwh: price,
    },
  ],
})
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status })
function fill() {
  fireEvent.change(screen.getByLabelText('Đơn giá mỗi kWh (VNĐ)'), {
    target: { value: '3500' },
  })
  fireEvent.change(screen.getByLabelText('Phí chiếm trụ mỗi phút (VNĐ)'), {
    target: { value: '500' },
  })
  fireEvent.change(screen.getByLabelText('Thời gian ân hạn (phút)'), {
    target: { value: '5' },
  })
}
it('loads empty context, saves first tariff and refreshes current rates on the station section', async () => {
  let saved = false
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      saved = true
      return response({ id: 'saved' }, 201)
    }
    return response({
      today,
      timezone: 'Asia/Ho_Chi_Minh',
      has_versions: saved,
      current: saved ? tariff(today) : null,
      upcoming: null,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  render(<StationTariff stationId="station-id" />)
  await screen.findByText('Trạm chưa có biểu giá đang áp dụng.')
  expect(screen.getByLabelText('Ngày hiệu lực')).toHaveValue(today)
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Lưu biểu giá' }))
  await screen.findByText('3.500 VNĐ/kWh')
  expect(screen.getByText(/Đã lưu biểu giá vào hệ thống/)).toBeInTheDocument()
  expect(screen.getByLabelText('Ngày hiệu lực')).toHaveValue('2026-10-11')
  expect(
    fetcher.mock.calls.filter((call) => call[1]?.method === 'POST'),
  ).toHaveLength(1)
})
it('keeps current tariff when a future version is created and shows upcoming separately', async () => {
  let saved = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method === 'POST') {
        saved = true
        return response({ id: 'future' }, 201)
      }
      return response({
        today,
        timezone: 'Asia/Ho_Chi_Minh',
        has_versions: true,
        current: tariff(today, '2500'),
        upcoming: saved ? tariff('2026-10-11') : null,
      })
    }),
  )
  render(<StationTariff stationId="station-id" />)
  await screen.findByText('2.500 VNĐ/kWh')
  expect(screen.getByLabelText('Ngày hiệu lực')).toHaveValue('2026-10-11')
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Lưu biểu giá' }))
  const heading = await screen.findByRole('heading', {
    name: 'Biểu giá sắp áp dụng',
  })
  expect(
    within(heading.parentElement!).getByText(/3.500 VNĐ\/kWh/),
  ).toBeInTheDocument()
  expect(screen.getByText('2.500 VNĐ/kWh')).toBeInTheDocument()
})
it.each([false, true])(
  'blocks invalid effective date before a request when hasVersions=%s',
  (hasVersions) => {
    const save = vi.fn()
    render(
      <TariffForm
        currentTariff={null}
        tariffToday={today}
        hasVersions={hasVersions}
        onSave={save}
      />,
    )
    fill()
    fireEvent.change(screen.getByLabelText('Ngày hiệu lực'), {
      target: { value: hasVersions ? today : '2026-10-11' },
    })
    expect(screen.getByRole('button', { name: 'Lưu biểu giá' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent(
      hasVersions ? 'ngày mai' : 'hôm nay',
    )
    expect(save).not.toHaveBeenCalled()
  },
)
it('blocks creation when context cannot be loaded', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => response({ detail: 'permission_denied' }, 403)),
  )
  render(<StationTariff stationId="foreign-station" />)
  await screen.findByRole('alert')
  expect(
    screen.queryByRole('button', { name: 'Lưu biểu giá' }),
  ).not.toBeInTheDocument()
})
it('distinguishes a committed save from a failed refresh and never sends another POST', async () => {
  let saved = false
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      saved = true
      return response({ id: 'saved' }, 201)
    }
    return saved
      ? response({}, 503)
      : response({
          today,
          timezone: 'Asia/Ho_Chi_Minh',
          has_versions: false,
          current: null,
          upcoming: null,
        })
  })
  vi.stubGlobal('fetch', fetcher)
  render(<StationTariff stationId="station-id" />)
  await screen.findByText('Trạm chưa có biểu giá đang áp dụng.')
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Lưu biểu giá' }))
  await screen.findByText(/Đã lưu biểu giá, nhưng chưa tải lại/)
  expect(
    fetcher.mock.calls.filter((call) => call[1]?.method === 'POST'),
  ).toHaveLength(1)
  await waitFor(() =>
    expect(
      screen.queryByRole('button', { name: 'Lưu biểu giá' }),
    ).not.toBeInTheDocument(),
  )
})
