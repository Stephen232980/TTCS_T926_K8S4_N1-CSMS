import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DriverNotificationCenter } from './DriverNotificationCenter'
import { DriverNotificationToastContainer } from './DriverNotificationToast'
const item = { id: 'event-1', session_id: 7, event_type: 'stop', title: 'Đã dừng sạc', message: 'Trạm A · 1 kWh · Tiền tạm tính: 3.000 đ', created_at: '2026-10-17T01:00:00Z', occurred_at: '2026-10-17T01:00:00Z', read_at: null }
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
it('restores unread inbox after remount without a charging snapshot, polls and does not duplicate a toast', async () => {
  vi.useFakeTimers()
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [item], next_cursor: null }) })
  vi.stubGlobal('fetch', fetchMock)
  const view = render(<DriverNotificationCenter ownerId="driver" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(screen.getByRole('region', { name: 'Thông báo phiên sạc' })).toHaveTextContent('1 kWh')
  for (let i = 0; i < 5; i++) await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  expect(screen.getAllByRole('button', { name: 'Đóng thông báo' })).toHaveLength(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(screen.queryByRole('region')).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([url]) => url.includes('/charging'))).toBe(false)
  expect(fetchMock.mock.calls.some(([, options]) => options.method === 'POST')).toBe(false)
  view.unmount()
  render(<DriverNotificationCenter ownerId="driver" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(screen.getByRole('region')).toHaveTextContent('Đã dừng sạc')
})
it('dismisses at eight seconds despite new callbacks and periodic parent renders', async () => {
  vi.useFakeTimers()
  const dismissed = vi.fn()
  const notification = { id: 'n', sessionId: 7, type: 'stop' as const, title: 'Stop', message: 'Estimate', createdAt: Date.now() }
  const view = render(<DriverNotificationToastContainer notifications={[notification]} onDismiss={id => dismissed(id)} />)
  for (let i = 0; i < 9; i++) {
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    view.rerender(<DriverNotificationToastContainer notifications={[notification]} onDismiss={id => dismissed(id)} />)
  }
  expect(dismissed).toHaveBeenCalledExactlyOnceWith('n')
})
it('only links to an invoice on a persisted invoice event and marks read explicitly', async () => {
  vi.useFakeTimers()
  const invoice = { ...item, event_type: 'invoice', title: 'Hóa đơn đã sẵn sàng' }
  let read = false
  const fetchMock = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') { read = true; return { ok: true, json: async () => ({ ...invoice, read_at: new Date().toISOString() }) } }
    return { ok: true, json: async () => ({ items: [invoice], next_cursor: null }) }
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<DriverNotificationCenter ownerId="driver" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(screen.getByRole('region').querySelector('a')).toHaveAttribute('href', '#driver-invoice-7')
  expect(read).toBe(false)
  act(() => { screen.getByRole('button', { name: /^Thông báo ·/ }).click() })
  await act(async () => { screen.getByRole('button', { name: 'Đánh dấu đã đọc' }).click() })
  expect(read).toBe(true)
  expect(screen.queryByRole('button', { name: 'Đánh dấu đã đọc' })).not.toBeInTheDocument()
})
it('recovers after an inbox network error', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ ok: true, json: async () => ({ items: [item], next_cursor: null }) }))
  render(<DriverNotificationCenter ownerId="driver" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(2001) })
  expect(screen.getByRole('region')).toHaveTextContent('Trạm A')
})


it('opens from the bell, closes by X or Escape, and does not mark read just by opening', async () => {
  const fetcher=vi.fn().mockResolvedValue({ok:true,json:async()=>({items:[item],next_cursor:null})})
  vi.stubGlobal('fetch',fetcher)
  render(<DriverNotificationCenter ownerId="driver" />)
  const bell=await screen.findByRole('button',{name:'Thông báo · 1 chưa đọc'})
  expect(screen.queryByRole('region',{name:'Danh sách thông báo'})).not.toBeInTheDocument()
  fireEvent.click(bell)
  expect(screen.getByRole('region',{name:'Danh sách thông báo'})).toBeVisible()
  fireEvent.click(screen.getByRole('button',{name:'Đóng danh sách thông báo'}))
  expect(bell).toHaveFocus()
  fireEvent.click(bell)
  fireEvent.keyDown(document,{key:'Escape'})
  expect(bell).toHaveAttribute('aria-expanded','false')
  expect(fetcher.mock.calls.some(([,options])=>options.method==='POST')).toBe(false)
})
