import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ChargerConfiguration } from './ChargerConfiguration'
const snapshot = { online: true, outcome: 'Accepted', keys: [{ key: 'HeartbeatInterval', value: '30', readonly: false, minimum: 30, maximum: 600 }, { key: 'MeterValueSampleInterval', value: '10', readonly: false, minimum: 5, maximum: 300 }], intents: [], reset_blocked: false }
const intent = { id: 'intent', key: 'HeartbeatInterval', value: 60, actual_value: '30', state: 'reboot_required', outcome: 'RebootRequired' }
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers() })
async function open() {
  render(<ChargerConfiguration chargerId="charger" allowed />)
  const details = screen.getByText('Cấu hình trụ').closest('details')!
  details.open = true; fireEvent(details, new Event('toggle'))
  await screen.findByRole('button', { name: 'Lưu' })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Lưu' })).toBeEnabled())
}
it('loads only when expanded and hides all controls without permission', () => {
  const fetcher = vi.spyOn(globalThis, 'fetch')
  const view = render(<ChargerConfiguration chargerId="charger" allowed />)
  expect(fetcher).not.toHaveBeenCalled()
  view.rerender(<ChargerConfiguration chargerId="charger" allowed={false} />)
  expect(screen.queryByText('Cấu hình trụ')).toBeNull()
})
it('validates bounds before submitting and does not claim success for Accepted', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, options) => options?.method === 'POST' ? response({ ...intent, state: 'queued' }, 202) : response(snapshot))
  await open()
  fireEvent.change(screen.getByLabelText('Giây'), { target: { value: '29' } })
  fireEvent.submit(screen.getByLabelText('Giây').closest('form')!)
  expect(screen.getByRole('alert')).toHaveTextContent('30–600')
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0)
  fireEvent.change(screen.getByLabelText('Giây'), { target: { value: '60' } })
  fireEvent.submit(screen.getByLabelText('Giây').closest('form')!)
  await waitFor(() => expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1))
  expect(screen.queryByText(/Đã xác minh/)).toBeNull()
})
it('preserves the same request ID when the response is lost', async () => {
  const bodies: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, options) => {
    if (options?.method !== 'POST') return response(snapshot)
    bodies.push(String(options.body))
    if (bodies.length === 1) throw new TypeError('Lost response')
    return response({ ...intent, state: 'queued' }, 202)
  })
  await open()
  fireEvent.change(screen.getByLabelText('Giây'), { target: { value: '60' } })
  fireEvent.submit(screen.getByLabelText('Giây').closest('form')!)
  fireEvent.click(await screen.findByRole('button', { name: 'Thử lại cùng yêu cầu' }))
  await waitFor(() => expect(bodies).toHaveLength(2))
  expect(bodies[0]).toBe(bodies[1])
})
it.each([false, true])('requires reset confirmation and blocks it while charging=%s', async blocked => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ ...snapshot, intents: [intent], reset_blocked: blocked }))
  render(<ChargerConfiguration chargerId="charger" allowed />)
  const details = screen.getByText('Cấu hình trụ').closest('details')!; details.open = true; fireEvent(details, new Event('toggle'))
  await screen.findByText(/Cần khởi động lại/)
  expect(fetcher.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  if (blocked) {
    expect(screen.queryByRole('button', { name: 'Khởi động lại mềm' })).toBeNull()
    expect(screen.getByText(/Chờ phiên kết thúc/)).toBeInTheDocument()
  } else {
    fireEvent.click(screen.getByRole('button', { name: 'Khởi động lại mềm' }))
    expect(screen.getByText('Khởi động lại mềm trụ này?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận' }))
    await waitFor(() => expect(fetcher.mock.calls.some(([url, options]) => String(url).endsWith('/reset') && options?.method === 'POST')).toBe(true))
  }
})
it('polls persisted status without sending another write and stops on unmount', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => response(snapshot))
  vi.useFakeTimers()
  render(<ChargerConfiguration chargerId="charger" allowed />)
  const details = screen.getByText('Cấu hình trụ').closest('details')!
  await act(async () => { details.open = true; fireEvent(details, new Event('toggle')); await vi.advanceTimersByTimeAsync(1) })
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(fetcher.mock.calls.some(([url]) => String(url).includes('refresh=false'))).toBe(true)
  const viewCount = fetcher.mock.calls.length
  cleanup()
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(fetcher).toHaveBeenCalledTimes(viewCount)
  expect(fetcher.mock.calls.every(([, options]) => !options?.method)).toBe(true)
})
it('does not offer another reset after confirmation while waiting for readback', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => response({ ...snapshot, intents: [{ ...intent, reset_requested: true }] }))
  render(<ChargerConfiguration chargerId="charger" allowed />)
  const details = screen.getByText('Cấu hình trụ').closest('details')!
  details.open = true; fireEvent(details, new Event('toggle'))
  await screen.findByText('Đang chờ trụ áp dụng cấu hình.')
  expect(screen.queryByRole('button', { name: 'Khởi động lại mềm' })).toBeNull()
})
it('does not replace a fresh device value with unchanged historical readback', async () => {
  const old = { ...intent, state: 'verified', outcome: 'Verified', actual_value: '60' }
  vi.spyOn(globalThis, 'fetch').mockImplementation(async url => response(String(url).includes('refresh=false') ? { ...snapshot, keys: [], intents: [old], outcome: 'Cached' } : { ...snapshot, keys: [{ ...snapshot.keys[0], value: '90' }], intents: [old] }))
  vi.useFakeTimers()
  render(<ChargerConfiguration chargerId="charger" allowed />)
  const details = screen.getByText('Cấu hình trụ').closest('details')!
  await act(async () => { details.open = true; fireEvent(details, new Event('toggle')); await vi.advanceTimersByTimeAsync(1) })
  expect(screen.getByText('90s')).toBeInTheDocument()
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(screen.getByText('90s')).toBeInTheDocument()
})
it('disables writes after a failed refresh and keeps that failure across status polls', async () => {
  let reads = 0
  vi.spyOn(globalThis, 'fetch').mockImplementation(async url => {
    if (String(url).includes('refresh=false')) return response({ ...snapshot, keys: [], outcome: 'Cached' })
    reads += 1
    return response(reads === 1 ? snapshot : { ...snapshot, keys: [], outcome: 'Timeout' })
  })
  vi.useFakeTimers()
  render(<ChargerConfiguration chargerId="charger" allowed />)
  const details = screen.getByText('Cấu hình trụ').closest('details')!
  await act(async () => { details.open = true; fireEvent(details, new Event('toggle')); await vi.advanceTimersByTimeAsync(1) })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Đọc lại' })); await vi.advanceTimersByTimeAsync(1) })
  expect(screen.getByRole('button', { name: 'Lưu' })).toBeDisabled()
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(screen.getByRole('button', { name: 'Lưu' })).toBeDisabled()
})
it('locks reset confirmation after a lost response and retries the original ID', async () => {
  const bodies: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, options) => {
    if (options?.method !== 'POST') return response({ ...snapshot, intents: [intent] })
    bodies.push(String(options.body))
    if (bodies.length === 1) throw new TypeError('Lost reset response')
    return response({ ...intent, state: 'resetting', reset_requested: true }, 202)
  })
  render(<ChargerConfiguration chargerId="charger" allowed />)
  const details = screen.getByText('Cấu hình trụ').closest('details')!
  details.open = true; fireEvent(details, new Event('toggle'))
  fireEvent.click(await screen.findByRole('button', { name: 'Khởi động lại mềm' }))
  fireEvent.click(screen.getByRole('button', { name: 'Xác nhận' }))
  await screen.findByRole('button', { name: 'Thử lại cùng yêu cầu' })
  expect(screen.getByRole('button', { name: 'Xác nhận' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Thử lại cùng yêu cầu' }))
  await waitFor(() => expect(bodies).toHaveLength(2))
  expect(bodies[0]).toBe(bodies[1])
})
