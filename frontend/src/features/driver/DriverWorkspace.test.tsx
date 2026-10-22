import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DriverWorkspace } from './DriverWorkspace'

vi.mock('../../components/maps/StationMap', () => ({ StationMap: () => <div aria-label="Bản đồ trạm sạc" /> }))
afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

it('syncs all selected-station prices after refresh without resetting connector selection', async () => {
  window.history.replaceState(null, '', '/#driver-stations')
  const initial = {id:'station-a',name:'Trạm A',address:'A',latitude:10.7,longitude:106.7,energy_rate_vnd_per_kwh:3000,idle_rate_vnd_per_minute:500,grace_minutes:2}
  let stations = [initial, {...initial,id:'station-b',name:'Trạm B',energy_rate_vnd_per_kwh:6000}]
  let fail = false
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/stations?')) return {ok:!fail,status:fail?503:200,json:async()=>({items:stations,total:stations.length,page:1,total_pages:1})}
    return {ok:true,json:async()=>url.includes('/connectors') ? {items:[{id:'connector',charge_point_code:'TRU-01',connector_number:1,status:'Available',can_start:true}]} : url.endsWith('/wallet') ? {balance:'100000',currency:'VND',status:'active'} : {session:null,start_request:null}}
  }))
  const user = userEvent.setup()
  render(<DriverWorkspace currentUser={{id:'driver',email:'driver@example.com',roles:['driver']}} onLogout={vi.fn()} />)
  await screen.findByText('Trạm A')
  await user.click(within(screen.getByText('Trạm A').closest('article')!).getByRole('button',{name:'Xem đầu nối'}))
  const summary = screen.getByRole('region',{name:'Giá và ví trước khi sạc'})
  expect(summary).toHaveTextContent('3.000 đ/kWh')
  await user.click(await screen.findByRole('button',{name:'TRU-01 · Đầu nối 1 · Sẵn sàng'}))
  await user.click(screen.getByLabelText('Tôi đã cắm súng sạc vào xe tại đầu nối đã chọn'))
  stations = [{...initial,energy_rate_vnd_per_kwh:4500,idle_rate_vnd_per_minute:700,grace_minutes:5},stations[1]]
  fireEvent(document,new Event('visibilitychange'))
  await waitFor(()=>expect(summary).toHaveTextContent('4.500 đ/kWh'))
  expect(summary).toHaveTextContent('700 đ/phút')
  expect(summary).toHaveTextContent('Miễn 5 phút')
  expect(screen.getByRole('button',{name:'TRU-01 · Đầu nối 1 · Sẵn sàng'})).toHaveAttribute('aria-pressed','true')
  expect(screen.getByLabelText('Tôi đã cắm súng sạc vào xe tại đầu nối đã chọn')).toBeChecked()
  fail=true
  fireEvent(document,new Event('visibilitychange'))
  await waitFor(()=>expect(document.querySelector('.driver-map-page [role="alert"]')).not.toBeNull())
  expect(summary).toHaveTextContent('4.500 đ/kWh')
  fail=false
  await user.click(screen.getByRole('button',{name:'Quay lại bản đồ và danh sách'}))
  fireEvent(document,new Event('visibilitychange'))
  await waitFor(()=>expect(within(screen.getByText('Trạm B').closest('article')!).getByRole('button',{name:'Xem đầu nối'})).toBeEnabled())
  await user.click(within(screen.getByText('Trạm B').closest('article')!).getByRole('button',{name:'Xem đầu nối'}))
  expect(screen.getByRole('region',{name:'Giá và ví trước khi sạc'})).toHaveTextContent('6.000 đ/kWh')
  stations=[]
  fireEvent(document,new Event('visibilitychange'))
  await waitFor(()=>expect(screen.getByRole('region',{name:'Giá và ví trước khi sạc'})).toHaveTextContent('Chưa có giá'))
})

it('preserves station search across connector navigation and only calls driver endpoints', async () => {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes('/charging/current') ? { session: null, start_request: null } : url.includes('/connectors') ? { items: [{ id: 'connector', charge_point_code: 'TRU-01', connector_number: 1, status: 'Reserved' }] } : { items: [{ id: 'station', name: 'Trạm thật', address: 'Địa chỉ', latitude: 10.7, longitude: 106.7, energy_rate_vnd_per_kwh: 2500 }], page: 1, total: 1, total_pages: 1 } }))
  vi.stubGlobal('fetch', fetchMock)
  const user = userEvent.setup()
  render(<DriverWorkspace currentUser={{ id: 'driver', email: 'driver@example.com', roles: ['driver'] }} onLogout={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Bạn chưa có phiên sạc đang diễn ra.' })
  await user.click(screen.getByRole('link', { name: 'Tìm trạm để bắt đầu sạc' }))
  await screen.findByText('Trạm thật')
  await user.type(screen.getByLabelText('Tên trạm hoặc địa chỉ'), 'Trạm')
  await user.click(screen.getByRole('button', { name: 'Tìm trạm' }))
  await screen.findByText('Trạm thật')
  await user.click(screen.getByRole('button', { name: 'Xem đầu nối' }))
  const reserved = await screen.findByRole('button', { name: 'TRU-01 · Đầu nối 1 · Đã đặt chỗ' })
  expect(screen.getByRole('region', { name: 'Giá và ví trước khi sạc' })).toHaveTextContent('2.500 đ/kWh')
  expect(reserved).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Bắt đầu sạc' })).toBeDisabled()
  expect(screen.getByRole('button', {name:'Quay lại bản đồ và danh sách'})).toBeInTheDocument()
  expect(screen.queryByText(/^Đặt chỗ của bạn/)).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Lịch sử đặt chỗ' })).toHaveAttribute('href', '#driver-reservations')
  await user.click(screen.getByRole('button', { name: 'Quay lại bản đồ và danh sách' }))
  expect(screen.getByLabelText('Tên trạm hoặc địa chỉ')).toHaveValue('Trạm')
  await waitFor(() => expect(screen.getByRole('button', { name: /Trạm thật/ })).toHaveAttribute('aria-pressed', 'true'))
  expect(fetchMock.mock.calls.every(([url]) => url.includes('/api/v1/driver/'))).toBe(true)
  expect(fetchMock.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
})
