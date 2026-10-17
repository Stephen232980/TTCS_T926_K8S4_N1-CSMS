import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DriverCharging } from './DriverCharging'

class FakeDriverStream {
  static instances: FakeDriverStream[] = []
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  listeners = new Map<string, () => void>()
  close = vi.fn()
  url: string
  options: EventSourceInit
  constructor(url: string, options: EventSourceInit) { this.url = url; this.options = options; FakeDriverStream.instances.push(this) }
  addEventListener(name: string, listener: () => void) { this.listeners.set(name, listener) }
  send(data: object) { this.onmessage?.({ data: JSON.stringify(data) }) }
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); FakeDriverStream.instances = [] })
const empty = { session: null, start_request: null }
const connectors = { items: [{ id: 'connector-one', charge_point_code: 'TRU-01', connector_number: 1, status: 'Available' }, { id: 'busy', charge_point_code: 'TRU-02', connector_number: 1, status: 'Reserved' }] }

it('allows starting on an owned confirmed reservation and blocks another driver reservation', async () => {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes('/connectors') ? { items: [
    { id: 'owned', charge_point_code: 'TRU-01', connector_number: 1, status: 'Reserved', own_reservation: true, can_start: true, available: false, reservation_capability: 'supported' },
    { id: 'other', charge_point_code: 'TRU-01', connector_number: 2, status: 'Reserved', own_reservation: false, can_start: false, available: false, reservation_capability: 'supported' },
  ] } : empty }))
  vi.stubGlobal('fetch', fetchMock)
  render(<DriverCharging stationId="station-one" ownerId="owner" />)
  const select = await screen.findByLabelText('Trụ và đầu nối')
  expect(screen.getByRole('option', { name: /Đầu nối 2/ })).toBeDisabled()
  await userEvent.selectOptions(select, 'owned')
  expect(await screen.findByText(/Đầu nối đang được giữ cho bạn/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('checkbox'))
  expect(screen.getByRole('button', { name: 'Bắt đầu sạc' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: 'Chọn giờ đến và đặt chỗ' })).not.toBeInTheDocument()
})
function mockApi(current: object = empty, result: object = { id: 'request-one', status: 'Accepted', deadline: new Date(Date.now() + 60000).toISOString() }) {
  const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => ({ ok: true, json: async () => options?.method === 'POST' ? result : url.includes('/connectors') ? connectors : current }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

it('shows empty state and guides the driver to the station map', async () => {
  mockApi()
  render(<DriverCharging />)
  expect(await screen.findByText('Bạn chưa có phiên sạc đang diễn ra.')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Tìm trạm để bắt đầu sạc' })).toHaveAttribute('href', '#driver-stations')
})

it('requires cable confirmation, blocks reserved connectors and posts only connector and request identity', async () => {
  const fetchMock = mockApi()
  const user = userEvent.setup()
  render(<DriverCharging stationId="station-one" stationName="Trạm tài xế" />)
  const select = await screen.findByLabelText('Trụ và đầu nối')
  const button = screen.getByRole('button', { name: 'Bắt đầu sạc' })
  expect(button).toBeDisabled()
  expect(screen.getByRole('option', { name: /TRU-02/ })).toBeDisabled()
  await user.selectOptions(select, 'connector-one')
  expect(button).toBeDisabled()
  await user.click(screen.getByRole('checkbox'))
  await user.click(button)
  expect(await screen.findByText(/Trụ đã chấp nhận/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Đang chờ trụ bắt đầu sạc…' })).toBeDisabled()
  expect(screen.getByText('Bạn chưa có phiên sạc đang diễn ra.')).toBeInTheDocument()
  const post = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST')!
  expect(post[0]).toContain('/api/v1/driver/charging/start')
  expect(Object.keys(JSON.parse(post[1].body)).sort()).toEqual(['connector_id', 'request_id'])
  expect(JSON.parse(post[1].body).connector_id).toBe('connector-one')
})

it('explains rejected starts and allows another attempt', async () => {
  mockApi(empty, { id: 'rejected', status: 'Rejected', deadline: null })
  const user = userEvent.setup()
  render(<DriverCharging stationId="station-one" />)
  await user.selectOptions(await screen.findByLabelText('Trụ và đầu nối'), 'connector-one')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Bắt đầu sạc' }))
  expect(await screen.findByText(/Trụ từ chối/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Bắt đầu sạc' })).toBeEnabled()
})

it.each([
  ['wallet_low', 'Số dư ví hiện tại chưa đạt mức tối thiểu', true],
  ['wallet_missing', 'Chưa tìm thấy ví của bạn', false],
  ['wallet_locked', 'Ví của bạn hiện đang bị khóa', false],
  ['tariff_unavailable', 'Chưa có thông tin giá sạc hợp lệ', false],
] as const)('shows the %s wallet eligibility reason', async (reason, message, canTopUp) => {
  const fetchMock = mockApi()
  fetchMock.mockImplementation(async (url: string, options?: RequestInit) => options?.method === 'POST'
    ? { ok: false, json: async () => ({ detail: reason }) }
    : { ok: true, json: async () => url.includes('/connectors') ? connectors : empty })
  const user = userEvent.setup()
  render(<DriverCharging stationId="station-one" />)
  await user.selectOptions(await screen.findByLabelText('Trụ và đầu nối'), 'connector-one')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Bắt đầu sạc' }))
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(message)
  if (canTopUp) {
    expect(screen.getByRole('link', { name: 'Nạp tiền' })).toHaveAttribute('href', '#driver-wallet')
  } else {
    expect(screen.queryByRole('link', { name: 'Nạp tiền' })).not.toBeInTheDocument()
  }
})

it('shows amounts and clears the denial when choosing a connector or station, then retries with a fresh identity', async () => {
  let funded = false
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      requests.push(JSON.parse(options.body as string).request_id)
      return funded ? { ok: true, json: async () => ({ id: 'funded', status: 'Accepted', deadline: new Date(Date.now() + 60000).toISOString() }) }
        : { ok: false, json: async () => ({ detail: { reason: 'wallet_low', balance_vnd: 20000, minimum_balance_vnd: 22500 } }) }
    }
    return { ok: true, json: async () => url.includes('/connectors') ? connectors : empty }
  }))
  const user = userEvent.setup()
  const view = render(<DriverCharging stationId="station-one" />)
  await user.selectOptions(await screen.findByLabelText('Trụ và đầu nối'), 'connector-one')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Bắt đầu sạc' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('20.000đ')
  expect(screen.getByRole('alert')).toHaveTextContent('22.500đ')
  await user.selectOptions(screen.getByLabelText('Trụ và đầu nối'), '')
  expect(screen.queryByRole('link', { name: 'Nạp tiền' })).not.toBeInTheDocument()
  await user.selectOptions(screen.getByLabelText('Trụ và đầu nối'), 'connector-one')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Bắt đầu sạc' }))
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  view.rerender(<DriverCharging stationId="station-two" />)
  await waitFor(() => expect(screen.queryByRole('link', { name: 'Nạp tiền' })).not.toBeInTheDocument())
  funded = true
  await user.selectOptions(screen.getByLabelText('Trụ và đầu nối'), 'connector-one')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Bắt đầu sạc' }))
  expect(await screen.findByText(/Trụ đã chấp nhận/)).toBeInTheDocument()
  expect(new Set(requests).size).toBe(3)
})

it('renders a delayed wallet rejection received over SSE and clears it on selection change', async () => {
  vi.stubGlobal('EventSource', FakeDriverStream)
  mockApi()
  const user = userEvent.setup()
  render(<DriverCharging stationId="station-one" />)
  await user.selectOptions(await screen.findByLabelText('Trụ và đầu nối'), 'connector-one')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Bắt đầu sạc' }))
  await act(async () => FakeDriverStream.instances[0].send({ session: null, start_request: { id: 'request-one', status: 'Rejected', reply_status: 'Accepted', connector_id: 'connector-one', rejection_reason: 'wallet_low', balance_vnd: 0, minimum_balance_vnd: 22500, deadline: null } }))
  expect(await screen.findByRole('alert')).toHaveTextContent('0đ')
  expect(screen.getByRole('alert')).toHaveTextContent('22.500đ')
  expect(screen.queryByText(/Trụ từ chối/)).not.toBeInTheDocument()
  await user.selectOptions(screen.getByLabelText('Trụ và đầu nối'), '')
  expect(screen.queryByRole('link', { name: 'Nạp tiền' })).not.toBeInTheDocument()
  await user.selectOptions(screen.getByLabelText('Trụ và đầu nối'), 'connector-one')
  expect(screen.queryByRole('link', { name: 'Nạp tiền' })).not.toBeInTheDocument()
})

it('opens the session view only after current confirms the matching started session', async () => {
  let current: object = empty
  const accepted = { id: 'request-one', status: 'Accepted', deadline: new Date(Date.now() + 60000).toISOString() }
  const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => ({
    ok: true, json: async () => options?.method === 'POST' ? accepted : url.includes('/connectors') ? connectors : current,
  }))
  vi.stubGlobal('fetch', fetchMock)
  const onSessionStarted = vi.fn()
  const user = userEvent.setup()
  render(<DriverCharging stationId="station-one" onSessionStarted={onSessionStarted} />)
  await user.selectOptions(await screen.findByLabelText('Trụ và đầu nối'), 'connector-one')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Bắt đầu sạc' }))
  expect(await screen.findByText(/Trụ đã chấp nhận/)).toBeInTheDocument()
  expect(onSessionStarted).not.toHaveBeenCalled()
  const session = { id: 3, station_name: 'Trạm xác nhận', charge_point_code: 'TRU-01', connector_number: 1, started_at: new Date().toISOString(), energy_kwh: 0, elapsed_seconds: 0, latest_meter_at: null, needs_attention: false }
  current = { session, start_request: { ...accepted, status: 'Started', session_id: 4 } }
  await screen.findByText('Trạm xác nhận', {}, { timeout: 2500 })
  expect(onSessionStarted).not.toHaveBeenCalled()
  current = { session, start_request: { ...accepted, status: 'Started', session_id: 3 } }
  await waitFor(() => expect(onSessionStarted).toHaveBeenCalledTimes(1), { timeout: 2500 })
})

it('updates actual energy and elapsed time within the one second poll', async () => {
  vi.useFakeTimers()
  let energy = 1.5
  const live = { id: 3, station_name: 'Trạm đang sạc', charge_point_code: 'TRU-01', connector_number: 1, started_at: '2026-10-02T01:00:00Z', energy_kwh: 0, elapsed_seconds: 125, latest_meter_at: '2026-10-02T01:02:05Z', needs_attention: false }
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({ ok: true, json: async () => ({ session: { ...live, energy_kwh: energy }, start_request: null }) })))
  render(<DriverCharging />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(screen.getByText('1,5')).toBeInTheDocument()
  expect(screen.getByText(/Trạm đang sạc/)).toBeInTheDocument()
  energy = 2.7
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  expect(screen.getByText('2,7')).toBeInTheDocument()
})

it('restores an accepted wait and shows recovery once its deadline expires', async () => {
  mockApi({ session: null, start_request: { id: 'waiting', status: 'Accepted', deadline: new Date(Date.now() - 1000).toISOString() } })
  render(<DriverCharging />)
  expect(await screen.findByText(/Sau 60 giây/)).toBeInTheDocument()
})

it('retains the same request key on a network failure and blocks start if current session is unknown', async () => {
  const fetchMock = mockApi()
  let count = 0
  fetchMock.mockImplementation(async (url: string, options?: RequestInit) => {
    if (options?.method === 'POST') { if (count++ === 0) throw new Error('Mất mạng. Hãy thử lại.'); return { ok: true, json: async () => ({ id: 'same', status: 'Rejected', deadline: null }) } }
    return { ok: true, json: async () => url.includes('/connectors') ? connectors : empty }
  })
  const user = userEvent.setup()
  render(<DriverCharging stationId="station-one" />)
  await user.selectOptions(await screen.findByLabelText('Trụ và đầu nối'), 'connector-one')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Bắt đầu sạc' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Mất mạng')
  await user.click(screen.getByRole('button', { name: 'Bắt đầu sạc' }))
  await waitFor(() => expect(screen.getByText(/Trụ từ chối/)).toBeInTheDocument())
  const posts = fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')
  expect(posts[0][1].body).toBe(posts[1][1].body)
})

const liveSession = { id: 7, station_name: 'Trạm SSE', charge_point_code: 'TRU-SSE', connector_number: 1, started_at: '2026-10-08T01:00:00Z', energy_kwh: 1.5, elapsed_seconds: 125, latest_meter_at: '2026-10-08T01:02:05Z', needs_attention: false }

it('receives SSE energy without polling and advances elapsed time locally', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeDriverStream)
  const fetchMock = mockApi()
  render(<DriverCharging />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  const stream = FakeDriverStream.instances[0]
  expect(stream.url).toContain('/api/v1/driver/charging/current/events')
  expect(stream.options.withCredentials).toBe(true)
  act(() => stream.send({ session: liveSession, start_request: null }))
  expect(screen.getByText('1,5')).toBeInTheDocument()
  await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
  expect(screen.getByText('2 phút 8 giây')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(1)
  act(() => stream.send({ session: { ...liveSession, energy_kwh: 2.7 }, start_request: null }))
  expect(screen.getByText('2,7')).toBeInTheDocument()
})

it('explains a late start blocked by station suspension', async () => {
  mockApi({ ...empty, start_request: { id: 'suspend-refusal', status: 'Rejected', deadline: null, rejection_reason: 'station_unavailable' } })
  render(<DriverCharging />)
  expect(await screen.findByText(/Trạm đã tạm ngừng hoặc không còn khả dụng/)).toBeInTheDocument()
})

it('keeps a newer SSE snapshot when the initial HTTP response arrives late', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeDriverStream)
  let resolve!: (response: object) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
  render(<DriverCharging />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  act(() => FakeDriverStream.instances[0].send({ session: liveSession, start_request: null }))
  await act(async () => { resolve({ ok: true, json: async () => empty }) })
  expect(screen.getByText('Trạm SSE')).toBeInTheDocument()
  expect(screen.queryByText('Bạn chưa có phiên sạc đang diễn ra.')).not.toBeInTheDocument()
})

it('restores a fresh snapshot after reconnect and closes the stream on unmount', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeDriverStream)
  mockApi({ session: liveSession, start_request: null })
  const view = render(<DriverCharging />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  const stream = FakeDriverStream.instances[0]
  await act(async () => stream.onerror?.())
  expect(screen.getByRole('alert')).toHaveTextContent('có thể đã cũ')
  act(() => stream.send({ session: { ...liveSession, energy_kwh: 4.5 }, start_request: null }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByText('4,5')).toBeInTheDocument()
  act(() => stream.send(empty))
  expect(screen.getByText('Bạn chưa có phiên sạc đang diễn ra.')).toBeInTheDocument()
  view.unmount()
  expect(stream.close).toHaveBeenCalledOnce()
  act(() => stream.send({ session: liveSession, start_request: null }))
})

it('clears private data and stops retries when stream authorization is denied', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeDriverStream)
  const fetchMock = mockApi({ session: liveSession, start_request: null })
  const unauthorized = vi.fn()
  window.addEventListener('csms:session-unauthorized', unauthorized)
  try {
    render(<DriverCharging />)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    const stream = FakeDriverStream.instances[0]
    act(() => stream.listeners.get('access-denied')?.())
    expect(stream.close).toHaveBeenCalled()
    expect(unauthorized).toHaveBeenCalledOnce()
    expect(screen.queryByText('Trạm SSE')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('không còn quyền')
    act(() => stream.send({ session: liveSession, start_request: null }))
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(screen.queryByText('Trạm SSE')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  } finally { window.removeEventListener('csms:session-unauthorized', unauthorized) }
})

it('reopens a malformed stream and waits for a valid recovery snapshot', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeDriverStream)
  mockApi()
  render(<DriverCharging />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  const first = FakeDriverStream.instances[0]
  act(() => first.onmessage?.({ data: 'not-json' }))
  expect(first.close).toHaveBeenCalledOnce()
  expect(screen.getByRole('alert')).toHaveTextContent('đang kết nối lại')
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  act(() => FakeDriverStream.instances[1].send({ session: liveSession, start_request: null }))
  expect(screen.getByText('Trạm SSE')).toBeInTheDocument()
  act(() => first.send(empty))
  expect(screen.getByText('Trạm SSE')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

<<<<<<< HEAD
it('emits an in-app toast and browser notification when an active session transitions to idle waiting for unplug', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeDriverStream)
  const mockNotification = vi.fn()
  Object.defineProperty(mockNotification, 'permission', { value: 'granted', writable: true })
  vi.stubGlobal('Notification', mockNotification)

  mockApi({ session: liveSession, start_request: null, awaiting_unplug: null })
  render(<DriverCharging />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  const stream = FakeDriverStream.instances[0]

  // Active session running
  act(() => stream.send({ session: liveSession, start_request: null, awaiting_unplug: null }))
  expect(screen.queryByText(/Đã dừng sạc — Vui lòng rút súng/)).not.toBeInTheDocument()

  // Transition to awaiting unplug
  const awaiting = { ...liveSession, ended_at: '2026-10-08T01:10:00Z', awaiting_unplug: true }
  act(() => stream.send({ session: null, start_request: null, awaiting_unplug: awaiting }))

  expect(screen.getByText('Đã dừng sạc — Vui lòng rút súng')).toBeInTheDocument()
  expect(screen.getByText(/tránh phát sinh phí chiếm trụ/)).toBeInTheDocument()
  expect(mockNotification).toHaveBeenCalledWith(
    expect.stringContaining('đã dừng'),
    expect.objectContaining({ body: expect.stringContaining('TRU-SSE') })
  )
})

it('emits a fault alert toast and browser notification when session flags needs_attention', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeDriverStream)
  const mockNotification = vi.fn()
  Object.defineProperty(mockNotification, 'permission', { value: 'granted', writable: true })
  vi.stubGlobal('Notification', mockNotification)

  mockApi({ session: liveSession, start_request: null })
  render(<DriverCharging />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  const stream = FakeDriverStream.instances[0]

  // Normal session
  act(() => stream.send({ session: liveSession, start_request: null }))
  expect(screen.queryByText('Cảnh báo sự cố sạc')).not.toBeInTheDocument()

  // Session encounters fault
  act(() => stream.send({ session: { ...liveSession, needs_attention: true }, start_request: null }))
  expect(screen.getByText('Cảnh báo sự cố sạc')).toBeInTheDocument()
  expect(screen.getByText(/gặp sự cố hoặc cần kiểm tra tại trụ/)).toBeInTheDocument()
  expect(mockNotification).toHaveBeenCalledWith(
    expect.stringContaining('Cảnh báo phiên sạc #7'),
    expect.any(Object)
  )
})

it('emits an invoice completion toast and browser notification when connector is released', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeDriverStream)
  const mockNotification = vi.fn()
  Object.defineProperty(mockNotification, 'permission', { value: 'granted', writable: true })
  vi.stubGlobal('Notification', mockNotification)

  mockApi({ session: liveSession, start_request: null })
  render(<DriverCharging />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  const stream = FakeDriverStream.instances[0]

  // Occupied session first
  act(() => stream.send({ session: liveSession, start_request: null, awaiting_unplug: null }))

  // Released session
  act(() => stream.send({ session: null, start_request: null, awaiting_unplug: null }))

  expect(screen.getByText('Phiên sạc hoàn tất')).toBeInTheDocument()
  expect(screen.getByText(/Hóa đơn phiên #7 đã được lập/)).toBeInTheDocument()
  const invoiceLink = screen.getByRole('link', { name: 'Xem hóa đơn phiên #7' })
  expect(invoiceLink).toHaveAttribute('href', '#driver-invoice-7')
  expect(mockNotification).toHaveBeenCalledWith(
    expect.stringContaining('Phiên sạc #7 hoàn tất'),
    expect.any(Object)
  )

  // Clicking dismiss closes the toast
  const closeButton = screen.getByRole('button', { name: 'Đóng thông báo' })
  await act(async () => { closeButton.click() })
  expect(screen.queryByText('Phiên sạc hoàn tất')).not.toBeInTheDocument()
})

it('allows requesting notification permission and auto-dismisses toast after 8 seconds', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeDriverStream)
  const requestPermission = vi.fn().mockResolvedValue('granted')
  const mockNotification = vi.fn()
  Object.defineProperty(mockNotification, 'permission', { value: 'default', writable: true })
  Object.defineProperty(mockNotification, 'requestPermission', { value: requestPermission, writable: true })
  vi.stubGlobal('Notification', mockNotification)

  mockApi({ session: liveSession, start_request: null })
  render(<DriverCharging />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })

  const permButton = screen.getByRole('button', { name: /Bật thông báo/ })
  await act(async () => { permButton.click() })
  expect(requestPermission).toHaveBeenCalledOnce()

  // Send an idle event to trigger toast
  const stream = FakeDriverStream.instances[0]
  act(() => stream.send({ session: liveSession, start_request: null }))
  const awaiting = { ...liveSession, ended_at: '2026-10-08T01:10:00Z', awaiting_unplug: true }
  act(() => stream.send({ session: null, start_request: null, awaiting_unplug: awaiting }))
  expect(screen.getByText('Đã dừng sạc — Vui lòng rút súng')).toBeInTheDocument()

  // Advance time by 8000ms -> toast auto-dismisses
  await act(async () => { await vi.advanceTimersByTimeAsync(8000) })
  expect(screen.queryByText('Đã dừng sạc — Vui lòng rút súng')).not.toBeInTheDocument()
=======
it('switches the driver selection but requires a fresh booking confirmation and request identity', async () => {
  let posts = 0
  const fetchMock=vi.fn().mockImplementation(async (url:string,options?:RequestInit)=> {
    if(options?.method==='POST') {
      posts++
      return posts===1 ? {ok:false,status:409,json:async()=>({detail:{reason:'connector_reserved',alternatives:[{connector_id:'second',charge_point_code:'CP-2',connector_number:2}]}})}
        : {ok:true,json:async()=>({status:'pending',expires_at:new Date().toISOString()})}
    }
    return {ok:true,json:async()=>url.includes('/connectors') ? {items:['first','second'].map((id,index)=>({id,charge_point_code:`CP-${index+1}`,connector_number:index+1,status:'Available',available:true,can_start:true,reservation_capability:'supported'}))}
      : url.includes('/policy') ? {fee_vnd:10000,version:1} : empty}
  })
  vi.stubGlobal('fetch',fetchMock)
  render(<DriverCharging stationId="station" ownerId="owner" />)
  const select=await screen.findByLabelText('Trụ và đầu nối')
  await userEvent.selectOptions(select,'first')
  await userEvent.click(screen.getByRole('button',{name:'Đặt trước đầu nối'}))
  await userEvent.click(await screen.findByLabelText('Tôi đồng ý.'))
  await userEvent.click(screen.getByRole('button',{name:'Xác nhận đặt chỗ'}))
  await userEvent.click(await screen.findByRole('button',{name:'Chọn CP-2 · Đầu nối 2'}))
  expect(select).toHaveValue('second')
  expect(posts).toBe(1)
  await userEvent.click(screen.getByRole('button',{name:'Đặt trước đầu nối'}))
  expect(await screen.findByLabelText('Tôi đồng ý.')).not.toBeChecked()
  expect(screen.getByRole('button',{name:'Xác nhận đặt chỗ'})).toBeDisabled()
  await userEvent.click(screen.getByLabelText('Tôi đồng ý.'))
  await userEvent.click(screen.getByRole('button',{name:'Xác nhận đặt chỗ'}))
  await waitFor(()=>expect(posts).toBe(2))
  const bodies=fetchMock.mock.calls.filter(([,options])=>options?.method==='POST').map(([,options])=>JSON.parse(options.body))
  expect(bodies[0].request_id).not.toBe(bodies[1].request_id)
  expect(bodies[1].connector_id).toBe('second')
  sessionStorage.clear()
>>>>>>> origin/develop
})
