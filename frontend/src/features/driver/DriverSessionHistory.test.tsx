import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DriverSessionHistory } from './DriverSessionHistory'
import { notifySessionUnauthorized } from '../auth/sessionEvents'
import { historyDate, readHistoryRoute } from './driverHistoryApi'

vi.mock('../auth/sessionEvents', () => ({ notifySessionUnauthorized: vi.fn() }))
vi.mock('./DriverInvoicePage', () => ({ DriverInvoicePage: ({sessionId,onBack,backLabel}: {sessionId?:number;onBack:()=>void;backLabel?:string}) => <section>Hóa đơn phiên {sessionId}<button onClick={onBack}>{backLabel}</button></section> }))
const item = { id: 41, station_id: 'station', station_name: 'Trạm Trung Tâm', charge_point_code: 'CP-01', connector_number: 1, started_at: '2026-10-18T23:30:00Z', ended_at: '2026-10-19T00:30:00Z', energy_kwh: '1.500000', latest_meter_wh: '2500', meter_start_wh: '1000', review_reasons: [], abnormal_since: null }
const page = { items: [item], total: 12, page: 1, total_pages: 2 }
const detail = { ...item, elapsed_seconds: 3600, needs_attention: false }
const response = (data: unknown, status=200) => ({ok:status===200,status,json:async()=>data})
beforeEach(() => { vi.clearAllMocks(); window.history.replaceState(null, '', '/#driver-history?page=2&state=closed') })
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })

it('keeps page/filter through session, invoice and return; supports direct links', async () => {
  const user=userEvent.setup()
  const fetcher=vi.fn().mockImplementation((url:string)=>Promise.resolve(response(url.includes('my-sessions')?page:detail)))
  vi.stubGlobal('fetch',fetcher)
  render(<DriverSessionHistory />)
  await user.click(await screen.findByRole('link',{name:'Phiên #41 · Trạm Trung Tâm'}))
  expect(window.location.hash).toContain('page=2&state=closed&session=41')
  expect(await screen.findByRole('heading',{name:'Phiên #41'})).toBeInTheDocument()
  expect(screen.getByText('1,5 kWh')).toBeInTheDocument()
  await user.click(screen.getByRole('button',{name:'Xem hóa đơn phiên này'}))
  expect(screen.getByText('Hóa đơn phiên 41')).toBeInTheDocument()
  expect(window.location.hash).toContain('view=invoice')
  await user.click(screen.getByRole('button',{name:'Quay lại phiên sạc'}))
  await user.click(await screen.findByRole('button',{name:'Quay lại lịch sử'}))
  await screen.findByRole('link',{name:'Phiên #41 · Trạm Trung Tâm'})
  expect(screen.getByLabelText('Trạng thái')).toHaveValue('closed')
  expect(window.location.hash).toBe('#driver-history?page=2&state=closed')
  expect(fetcher).toHaveBeenCalledWith('/api/v1/charging/my-sessions?page=2&page_size=10&state=closed',expect.objectContaining({credentials:'include',signal:expect.any(AbortSignal)}))
})

it('hides stale rows while changing filters and ignores a late aborted request', async () => {
  const user=userEvent.setup()
  let finishOld: ((value:ReturnType<typeof response>)=>void)|undefined
  const fetcher=vi.fn().mockImplementation((url:string)=>url.includes('state=closed')?new Promise(resolve=>{finishOld=resolve}):Promise.resolve(response({...page,items:[{...item,id:72}],total:1,total_pages:1})))
  vi.stubGlobal('fetch',fetcher)
  render(<DriverSessionHistory />)
  await user.selectOptions(screen.getByLabelText('Trạng thái'),'review')
  await screen.findByRole('link',{name:'Phiên #72 · Trạm Trung Tâm'})
  await act(async()=>{finishOld?.(response(page))})
  expect(screen.queryByRole('link',{name:'Phiên #41 · Trạm Trung Tâm'})).not.toBeInTheDocument()
  expect(window.location.hash).toBe('#driver-history?page=1&state=review')
  const oldSignal=fetcher.mock.calls[0][1].signal as AbortSignal
  expect(oldSignal.aborted).toBe(true)
})

it('clears previous results on page failure and allows retry', async () => {
  window.history.replaceState(null,'','/#driver-history')
  const user=userEvent.setup()
  const fetcher=vi.fn().mockResolvedValueOnce(response(page)).mockResolvedValueOnce(response({},500)).mockResolvedValueOnce(response({...page,items:[{...item,id:55}]}))
  vi.stubGlobal('fetch',fetcher)
  render(<DriverSessionHistory />)
  await screen.findByRole('link',{name:'Phiên #41 · Trạm Trung Tâm'})
  await user.click(screen.getByRole('button',{name:'Trang sau'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Không tải được lịch sử')
  expect(screen.queryByText(/Phiên #41/)).not.toBeInTheDocument()
  await user.click(screen.getByRole('button',{name:'Thử lại'}))
  expect(await screen.findByRole('link',{name:'Phiên #55 · Trạm Trung Tâm'})).toBeInTheDocument()
})

it('renders the empty state', async () => {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({items:[],total:0,page:1,total_pages:0})))
  render(<DriverSessionHistory />)
  expect(await screen.findByRole('heading',{name:'Chưa có phiên sạc phù hợp'})).toBeInTheDocument()
  expect(screen.queryByRole('navigation',{name:'Phân trang lịch sử phiên sạc'})).not.toBeInTheDocument()
})

it('honors browser navigation to a different session and masks old details', async () => {
  window.history.replaceState(null,'','/#driver-history?session=41')
  const fetcher=vi.fn().mockResolvedValueOnce(response(detail)).mockResolvedValueOnce(response({},403))
  vi.stubGlobal('fetch',fetcher)
  render(<DriverSessionHistory />)
  await screen.findByRole('heading',{name:'Phiên #41'})
  act(()=>{window.history.replaceState(null,'','/#driver-history?session=99');window.dispatchEvent(new PopStateEvent('popstate'))})
  expect(await screen.findByRole('alert')).toHaveTextContent('không có quyền')
  expect(screen.queryByRole('heading',{name:'Phiên #41'})).not.toBeInTheDocument()
  expect(screen.queryByRole('button',{name:'Xem hóa đơn phiên này'})).not.toBeInTheDocument()
})

it('opens invoice deep links on reload and validates URL query values', async () => {
  window.history.replaceState(null,'','/#driver-history?page=-1&state=bad&session=41&view=invoice')
  expect(readHistoryRoute()).toEqual({page:1,state:'all',session:41,invoice:true})
  render(<DriverSessionHistory />)
  expect(screen.getByText('Hóa đơn phiên 41')).toBeInTheDocument()
  expect(historyDate('2026-10-18T23:30:00Z')).toContain('19/10/26')
})

it('notifies the auth flow on 401 and offers a retry', async () => {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({},401)))
  render(<DriverSessionHistory />)
  await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('Phiên đăng nhập đã hết hạn'))
  expect(screen.getByRole('button',{name:'Thử lại'})).toBeInTheDocument()
  expect(notifySessionUnauthorized).toHaveBeenCalledOnce()
})


it('keeps missing final energy unknown while using readings for open sessions', async () => {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({...page,items:[{...item,energy_kwh:null},{...item,id:42,ended_at:null,energy_kwh:null}]})))
  render(<DriverSessionHistory />)
  expect(await screen.findByText('Chưa có số đo')).toBeInTheDocument()
  expect(screen.getByText('1,5 kWh')).toBeInTheDocument()
})


it('resets a session deep link when returning to history from the account menu', async () => {
  const { DriverWorkspace } = await import('./DriverWorkspace')
  window.history.replaceState(null,'','/#driver-history?page=2&state=closed&session=41')
  vi.stubGlobal('fetch',vi.fn().mockImplementation((url:string)=>Promise.resolve(response(url.includes('/notifications')?{items:[],next_cursor:null}:url.includes('my-sessions')?page:detail))))
  render(<DriverWorkspace currentUser={{id:'driver',email:'driver@example.com',roles:['driver']}} onLogout={async()=>{}} />)
  expect(await screen.findByRole('heading',{name:'Phiên #41'})).toBeInTheDocument()
  const user=userEvent.setup()
  await user.click(screen.getByRole('button',{name:'Tài khoản'}))
  await user.click(screen.getByRole('button',{name:'Lịch sử phiên sạc'}))
  expect(await screen.findByRole('link',{name:'Phiên #41 · Trạm Trung Tâm'})).toBeInTheDocument()
  expect(screen.queryByRole('heading',{name:'Phiên #41'})).not.toBeInTheDocument()
  expect(window.location.hash).toBe('#driver-history')
})
