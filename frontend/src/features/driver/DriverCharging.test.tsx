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
