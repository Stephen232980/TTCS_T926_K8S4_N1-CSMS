import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ReservationForm } from './ReservationForm'
import { DriverReservations } from './DriverReservations'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
const now = new Date().toISOString()
const item = { id: 'booking-one', station_id: 'station', station_name: 'Trạm demo', connector_id: 'connector', charge_point_code: 'CP-1', connector_number: 1, status: 'active', created_at: now, arrival_at: now, expires_at: now, updated_at: now, can_cancel: true, no_show_exempt: false, outcome: 'Accepted', session_id: null }
const page = { items: [item], page: 1, total_pages: 1, total: 1, generated_at: now }
const response = (value: unknown) => ({ ok: true, status: 202, json: async () => value })

it('checks capability without claiming a confirmed booking', async () => {
  const fetch = vi.fn().mockResolvedValue(response({ status: 'unverified' }))
  vi.stubGlobal('fetch', fetch)
  const changed = vi.fn()
  render(<ReservationForm connectorId="connector" capability="unverified" available ownerId="owner" onChanged={changed} />)
  await userEvent.click(screen.getByRole('button', { name: 'Kiểm tra hỗ trợ đặt chỗ' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Đang kiểm tra hỗ trợ')
  expect(fetch.mock.calls[0][0]).toContain('/capabilities')
  expect(changed).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button', { name: 'Gửi yêu cầu đặt chỗ' })).not.toBeInTheDocument()
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
  await userEvent.click(screen.getByRole('button', { name: 'Chọn giờ đến và đặt chỗ' }))
  await userEvent.click(screen.getByRole('button', { name: 'Gửi yêu cầu đặt chỗ' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Kết quả gửi chưa rõ')
  const original = fetch.mock.calls.find(([, options]) => options?.method === 'POST')![1].body
  first.unmount()
  render(<ReservationForm {...props} available={false} />)
  expect(screen.getByLabelText('Giờ đến')).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Thử lại cùng yêu cầu đặt chỗ' }))
  expect(fetch.mock.calls.filter(([, options]) => options?.method === 'POST')[1][1].body).toBe(original)
  expect(await screen.findByRole('status')).toHaveTextContent('Theo dõi xác nhận')
  expect(sessionStorage.getItem('csms:reservation:owner:connector')).toBeNull()
})

it('ignores a malformed persisted date instead of crashing the charging view', () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({fee_vnd:0,version:0})))
  sessionStorage.setItem('csms:reservation:owner:connector', JSON.stringify({ request_id: 'key', connector_id: 'connector', arrival_at: 'invalid' }))
  render(<ReservationForm connectorId="connector" capability="supported" available ownerId="owner" onChanged={() => {}} />)
  expect(screen.getByRole('button', { name: 'Chọn giờ đến và đặt chỗ' })).toBeEnabled()
})

it('requires explicit acceptance of the quoted fee and sends its exact version', async () => {
  const fetch = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => response(options?.method === 'POST' ? {...item,status:'pending'} : {fee_vnd:10000,version:3}))
  vi.stubGlobal('fetch', fetch)
  render(<ReservationForm connectorId="connector" capability="supported" available ownerId="owner" onChanged={() => {}} />)
  await screen.findByText(/Phí không đến: 10.000đ/)
  await userEvent.click(screen.getByRole('button', {name:'Chọn giờ đến và đặt chỗ'}))
  expect(screen.getByRole('button', {name:'Gửi yêu cầu đặt chỗ'})).toBeDisabled()
  await userEvent.click(screen.getByRole('checkbox'))
  await userEvent.click(screen.getByRole('button', {name:'Gửi yêu cầu đặt chỗ'}))
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
