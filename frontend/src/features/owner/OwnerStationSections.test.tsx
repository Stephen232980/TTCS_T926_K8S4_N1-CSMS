import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnerWorkspace } from './OwnerWorkspace'
import { MockStationApi } from '../stations/api/mockStationApi'
import { MockChargePointApi } from '../chargePoints/api/mockChargePointApi'

vi.mock('./TariffHistoryPanel', () => ({
  TariffHistoryPanel: ({ stationId }: { stationId: string }) => <h2>Lịch sử biểu giá {stationId}</h2>,
}))

afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })

it('gives equipment and tariffs separate space while keeping the selected station', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [], total_pages: 1 }))))
  const user = userEvent.setup()
  render(<OwnerWorkspace
    currentUser={{ id: 'owner', email: 'owner@example.com', roles: ['station_owner'] }}
    onLogout={vi.fn()}
    stationApi={new MockStationApi([{
      id: 'station-test', name: 'Trạm thử', address: 'Địa chỉ thử', latitude: 10, longitude: 106,
      status: 'active', createdAt: '', updatedAt: '',
    }], 0)}
    chargePointApi={new MockChargePointApi([], 0)}
  />)
  await user.click(await screen.findByRole('button', { name: 'Xem chi tiết Trạm thử' }))
  const sections = screen.getByRole('navigation', { name: 'Nội dung trạm' })
  expect(screen.getByRole('heading', { name: 'Khu sạc' })).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Biểu giá của trạm' })).not.toBeInTheDocument()
  await user.click(within(sections).getByRole('button', { name: 'Biểu giá' }))
  expect(screen.getByRole('heading', { name: 'Lịch sử biểu giá station-test' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Khu sạc' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Thêm trụ' })).not.toBeInTheDocument()
  await user.click(within(sections).getByRole('button', { name: 'Khu sạc' }))
  expect(screen.getByRole('heading', { name: 'Trạm thử' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Thêm trụ' })).toBeInTheDocument()
  await user.click(screen.getByRole('link', { name: 'Biểu giá' }))
  expect(screen.getByRole('heading', { name: 'Lịch sử biểu giá station-test' })).toBeInTheDocument()
})

it('restores a station tariff link and follows browser history changes', async () => {
  window.history.replaceState(null, '', '/#tariffs?station=station-test')
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [], total_pages: 1 }))))
  render(<OwnerWorkspace
    currentUser={{ id: 'owner', email: 'owner@example.com', roles: ['station_owner'] }}
    onLogout={vi.fn()}
    stationApi={new MockStationApi([{ id: 'station-test', name: 'Trạm thử', address: 'Địa chỉ', latitude: 10, longitude: 106, status: 'active', createdAt: '', updatedAt: '' }], 0)}
    chargePointApi={new MockChargePointApi([], 0)}
  />)
  expect(await screen.findByRole('heading', { name: 'Lịch sử biểu giá station-test' })).toBeInTheDocument()
  window.location.hash = '#stations?station=station-test'
  expect(await screen.findByRole('heading', { name: 'Khu sạc' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Trạm thử' })).toBeInTheDocument()
})

it('finds a charger beyond the first page and reports no matching chargers', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [], total_pages: 1 }))))
  const user = userEvent.setup()
  const points = Array.from({ length: 21 }, (_, i) => ({ id: `cp-${i}`, stationId: 'station-test', code: `CP-${i + 1}`, name: null, status: 'available', codeLockedAt: null, connectors: [], createdAt: '', updatedAt: '' }))
  render(<OwnerWorkspace
    currentUser={{ id: 'owner', email: 'owner@example.com', roles: ['station_owner'] }}
    onLogout={vi.fn()}
    stationApi={new MockStationApi([{ id: 'station-test', name: 'Trạm thử', address: 'Địa chỉ', latitude: 10, longitude: 106, status: 'active', createdAt: '', updatedAt: '' }], 0)}
    chargePointApi={new MockChargePointApi(points, 0)}
  />)
  await user.click(await screen.findByRole('button', { name: 'Xem chi tiết Trạm thử' }))
  await screen.findByText('CP-1')
  const search = screen.getByRole('searchbox', { name: 'Tìm trụ trong trạm' })
  await user.type(search, 'CP-21')
  expect(await screen.findByText('CP-21')).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByText('CP-1')).not.toBeInTheDocument())
  await user.clear(search)
  await user.type(search, 'missing')
  expect(await screen.findByText(/Không tìm thấy trụ khớp/)).toBeInTheDocument()
})

it('opens connector 1 from the charger card and preserves an explicit connector choice', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [], total_pages: 1 }))))
  const user = userEvent.setup()
  render(<OwnerWorkspace
    currentUser={{ id: 'owner', email: 'owner@example.com', roles: ['station_owner'] }}
    onLogout={vi.fn()}
    stationApi={new MockStationApi([{ id: 'station-test', name: 'Trạm thử', address: 'Địa chỉ', latitude: 10, longitude: 106, status: 'active', createdAt: '', updatedAt: '' }], 0)}
    chargePointApi={new MockChargePointApi([{ id: 'cp', stationId: 'station-test', code: 'CP-DEMO', name: 'Trụ demo', status: 'available', codeLockedAt: null, createdAt: '', updatedAt: '', connectors: [2, 1].map(n => ({ id: `connector-${n}`, connectorNumber: n, status: 'available', createdAt: '', updatedAt: '' })) }], 0)}
  />)
  await user.click(await screen.findByRole('button', { name: 'Xem chi tiết Trạm thử' }))
  const open = await screen.findByRole('button', { name: 'Xem trụ Trụ demo' })
  await user.click(open)
  expect(screen.getByText('Đầu nối 1', { exact: true })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Sao chép mã trụ' })).toHaveClass('secondary-button')
  await user.click(screen.getByRole('button', { name: /CP-DEMO · Đầu nối 2:/ }))
  expect(screen.getByText('Đầu nối 2', { exact: true })).toBeInTheDocument()
  await user.click(open.closest('article')!)
  expect(screen.getByText('Đầu nối 1', { exact: true })).toBeInTheDocument()
})
