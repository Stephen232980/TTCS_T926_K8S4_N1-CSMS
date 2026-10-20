import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ReservationForm } from './ReservationForm'
import { DriverReservations } from './DriverReservations'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); sessionStorage.clear() })
const now = new Date().toISOString()
const item = { id: 'booking-one', station_id: 'station', station_name: 'Trạm demo', connector_id: 'connector', charge_point_code: 'CP-1', connector_number: 1, status: 'active', created_at: now, arrival_at: now, expires_at: now, updated_at: now, can_cancel: true, no_show_exempt: false, outcome: 'Accepted', session_id: null }
const page = { items: [item], page: 1, total_pages: 1, total: 1, generated_at: now }
const response = (value: unknown) => ({ ok: true, status: 202, json: async () => value })

it('checks capability without claiming a confirmed booking', async () => {
  const fetch = vi.fn().mockResolvedValue(response({ status: 'unverified' }))
  vi.stubGlobal('fetch', fetch)
  const changed = vi.fn()
  render(<ReservationForm connectorId="connector" capability="unverified" available ownerId="owner" onChanged={changed} />)
  await userEvent.click(screen.getByRole('button', { name: 'Đặt trước đầu nối' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Đang kiểm tra hỗ trợ')
  expect(fetch.mock.calls[0][0]).toContain('/capabilities')
  expect(changed).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button', { name: 'Xác nhận đặt chỗ' })).not.toBeInTheDocument()
})

it('opens a named popup and cancelling submits no reservation and restores focus', async () => {
  const fetch=vi.fn().mockResolvedValue(response({fee_vnd:0,version:0}))
  vi.stubGlobal('fetch',fetch)
  render(<ReservationForm connectorId="connector" capability="supported" available ownerId="owner" onChanged={vi.fn()} />)
  const trigger=screen.getByRole('button',{name:'Đặt trước đầu nối'})
  await userEvent.click(trigger)
  expect(screen.getByRole('dialog',{name:'Đặt trước đầu nối'})).toBeVisible()
  await userEvent.click(screen.getByRole('button',{name:'Hủy'}))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  expect(fetch.mock.calls.some(([, options])=>options?.method==='POST')).toBe(false)
})

it('shows only one action until opened and resolves the probe when polling reports support', async () => {
  const fetch = vi.fn().mockImplementation(async (url: string) => response(url.includes('/capabilities') ? {status:'unverified'} : {fee_vnd:0,version:0}))
  vi.stubGlobal('fetch', fetch)
  const props = {connectorId:'connector', capability:'unverified', available:true, ownerId:'owner', onChanged:vi.fn()}
  const view = render(<ReservationForm {...props} />)
  expect(screen.getAllByRole('button')).toHaveLength(1)
  expect(screen.queryByText(/Yêu cầu giữ ngay/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', {name:'Đặt trước đầu nối'}))
  view.rerender(<ReservationForm {...props} capability="supported" />)
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  expect(await screen.findByText(/Giữ chỗ ngay trong 15 phút/)).toBeVisible()
  await waitFor(() => expect(screen.getByRole('button', {name:'Xác nhận đặt chỗ'})).toBeEnabled())
})

it('ends an unanswered probe with an actionable error and allows retry', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({status:'unverified'})))
  render(<ReservationForm connectorId="connector" capability="unverified" available ownerId="owner" onChanged={vi.fn()} />)
  await act(async () => {fireEvent.click(screen.getByRole('button', {name:'Đặt trước đầu nối'}))})
  await act(async () => {await vi.advanceTimersByTimeAsync(20001)})
  expect(screen.getByRole('alert')).toHaveTextContent('Chưa nhận được kết quả từ trụ')
  expect(screen.getByRole('button', {name:'Đặt trước đầu nối'})).toBeEnabled()
})

it('aborts a stalled capability HTTP request and restores the retry action', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockImplementation((_url: string, options: RequestInit) => new Promise((_resolve,reject) => {
    options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted','AbortError')))
  })))
  render(<ReservationForm connectorId="connector" capability="unverified" available ownerId="owner" onChanged={vi.fn()} />)
  await act(async () => {fireEvent.click(screen.getByRole('button', {name:'Đặt trước đầu nối'}))})
  await act(async () => {await vi.advanceTimersByTimeAsync(10001)})
  expect(screen.getByRole('alert')).toHaveTextContent('Máy chủ chưa phản hồi')
  expect(screen.getByRole('button', {name:'Đặt trước đầu nối'})).toBeEnabled()
})

it.each(['network', 'server'] as const)('retries the identical persisted request after an ambiguous %s failure', async (failure) => {
  let posted = 0
  const fetch = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => {
    if (options?.method !== 'POST') return response({fee_vnd:0,version:0})
    if (++posted === 1) {
      if (failure === 'network') throw new TypeError('network')
      return {ok:false,status:500,json:async()=>({detail:'internal_error'})}
    }
    return response({ ...item, status: 'pending' })
  })
  vi.stubGlobal('fetch', fetch)
  const props = { connectorId: 'connector', capability: 'supported', available: true, ownerId: 'owner', onChanged: vi.fn() }
  const first = render(<ReservationForm {...props} />)
  await userEvent.click(screen.getByRole('button', { name: 'Đặt trước đầu nối' }))
  await userEvent.click(screen.getByRole('button', { name: 'Xác nhận đặt chỗ' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Kết quả gửi chưa rõ')
  const original = fetch.mock.calls.find(([, options]) => options?.method === 'POST')![1].body
  first.unmount()
  render(<ReservationForm {...props} available={false} />)
  expect(screen.queryByLabelText('Giờ đến')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Thử lại cùng yêu cầu đặt chỗ' }))
  expect(fetch.mock.calls.filter(([, options]) => options?.method === 'POST')[1][1].body).toBe(original)
  expect(await screen.findByRole('status')).toHaveTextContent('Theo dõi xác nhận')
  expect(sessionStorage.getItem('csms:reservation:owner:connector')).toBeNull()
})

it('ignores a malformed persisted date instead of crashing the charging view', () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({fee_vnd:0,version:0})))
  sessionStorage.setItem('csms:reservation:owner:connector', JSON.stringify({ request_id: 'key', connector_id: 'connector', arrival_at: 'invalid' }))
  render(<ReservationForm connectorId="connector" capability="supported" available ownerId="owner" onChanged={() => {}} />)
  expect(screen.getByRole('button', { name: 'Đặt trước đầu nối' })).toBeEnabled()
})

it('requires explicit acceptance of the quoted fee and sends its exact version', async () => {
  const fetch = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => response(options?.method === 'POST' ? {...item,status:'pending'} : {fee_vnd:10000,version:3}))
  vi.stubGlobal('fetch', fetch)
  render(<ReservationForm connectorId="connector" capability="supported" available ownerId="owner" onChanged={() => {}} />)
  await userEvent.click(screen.getByRole('button', {name:'Đặt trước đầu nối'}))
  expect(screen.getByRole('button', {name:'Xác nhận đặt chỗ'})).toBeDisabled()
  await userEvent.click(screen.getByRole('checkbox'))
  await userEvent.click(screen.getByRole('button', {name:'Xác nhận đặt chỗ'}))
  const body = JSON.parse(fetch.mock.calls.find(([, options]) => options?.method === 'POST')![1].body)
  expect(body.accepted_fee_vnd).toBe(10000)
  expect(body.accepted_policy_version).toBe(3)
})

it('retains the cancellation key across timeout and presents cancel_pending as unconfirmed', async () => {
  let posted = 0
  const fetch = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      if (++posted === 1) throw new TypeError('network')
      return response({ ...item, status: 'cancel_pending', can_cancel: false, no_show_exempt: true })
    }
    return response(posted >= 2 ? { ...page, items: [{ ...item, status: 'cancel_pending', can_cancel: false, no_show_exempt: true }] } : page)
  })
  vi.stubGlobal('fetch', fetch)
  render(<DriverReservations ownerId="owner" />)
  await screen.findByText('Trạm demo')
  await userEvent.click(screen.getByText(/^Đặt chỗ của bạn/))
  await userEvent.click(screen.getByRole('button', { name: 'Hủy đặt chỗ' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Kết quả hủy chưa rõ')
  await userEvent.click(screen.getByRole('button', { name: 'Hủy đặt chỗ' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Hủy đặt chỗ' })).not.toBeInTheDocument())
  const posts = fetch.mock.calls.filter(([, options]) => options?.method === 'POST')
  expect(posts[0][1].body).toBe(posts[1][1].body)
  expect(screen.getByText('Đang chờ xác nhận hủy')).toBeInTheDocument()
  expect(screen.getByText(/Chưa có xác nhận cuối từ trụ/)).toBeInTheDocument()
  expect(screen.getByText('Đã ghi nhận miễn phí không đến.')).toBeInTheDocument()
})

it('offers compatible alternatives and selecting one closes without submitting again', async () => {
  const selected = vi.fn()
  const fetch = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => options?.method === 'POST'
    ? {ok:false,status:409,json:async()=>({detail:{reason:'connector_reserved',alternatives:[{connector_id:'second',charge_point_code:'CP-2',connector_number:2}]}})}
    : response({fee_vnd:0,version:0}))
  vi.stubGlobal('fetch',fetch)
  render(<ReservationForm connectorId="connector" capability="supported" available ownerId="owner" onChanged={vi.fn()} onSelectAlternative={selected} />)
  await userEvent.click(screen.getByRole('button',{name:'Đặt trước đầu nối'}))
  await userEvent.click(screen.getByRole('button',{name:'Xác nhận đặt chỗ'}))
  await userEvent.click(await screen.findByRole('button',{name:'Chọn CP-2 · Đầu nối 2'}))
  expect(selected).toHaveBeenCalledWith('second')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(fetch.mock.calls.filter(([,options])=>options?.method==='POST')).toHaveLength(1)
  expect(sessionStorage.getItem('csms:reservation:owner:connector')).toBeNull()
})

it.each(['connector_reserved', {reason:'connector_reserved',alternatives:[null,{}, {connector_id:'bad',charge_point_code:'CP',connector_number:-1}]}])('handles legacy or malformed conflict hints with an empty state', async detail => {
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async (_url: string,options?:RequestInit)=>options?.method==='POST'
    ? {ok:false,status:409,json:async()=>({detail})} : response({fee_vnd:0,version:0})))
  render(<ReservationForm connectorId="connector" capability="supported" available ownerId="owner" onChanged={vi.fn()} />)
  await userEvent.click(screen.getByRole('button',{name:'Đặt trước đầu nối'}))
  await userEvent.click(screen.getByRole('button',{name:'Xác nhận đặt chỗ'}))
  expect(await screen.findByText(/Chưa có đầu nối thay thế phù hợp/)).toBeInTheDocument()
})


it('only creates immediate reservations with no scheduled arrival', async () => {
  const fetch = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => response(options?.method === 'POST' ? {...item, status:'pending'} : {fee_vnd:0, version:0}))
  vi.stubGlobal('fetch', fetch)
  render(<ReservationForm connectorId="connector" capability="supported" available ownerId="owner" onChanged={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', {name:'Đặt trước đầu nối'}))
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Thời gian đến')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', {name:'Xác nhận đặt chỗ'}))
  const body = JSON.parse(fetch.mock.calls.find(([, options]) => options?.method === 'POST')![1].body)
  expect(body.arrival_at).toBeNull()
})

it('preserves a persisted scheduled request when retrying after the policy change', async () => {
  const previous = {request_id:'old-key', connector_id:'connector', arrival_at:'2026-10-20T08:00:00Z', accepted_fee_vnd:0, accepted_policy_version:0}
  sessionStorage.setItem('csms:reservation:owner:connector', JSON.stringify(previous))
  const fetch = vi.fn().mockResolvedValue(response({...item, status:'pending'}))
  vi.stubGlobal('fetch', fetch)
  render(<ReservationForm connectorId="connector" capability="supported" available={false} ownerId="owner" onChanged={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', {name:'Thử lại cùng yêu cầu đặt chỗ'}))
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(previous)
})
