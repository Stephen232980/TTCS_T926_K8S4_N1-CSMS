import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { StationPowerPage } from './StationPowerPage'

const snapshot = {
  station_id: 'station', version: 1, limit_kw: '30', applied_limit_w: 30000,
  total_rated_w: 66000, over_registered: true, enabled: false, state: 'disabled', issue: null,
  zero_limit_verified: false, offline_retention_verified: false, verification_note: '',
  connectors: [1, 2, 3].map(number => ({ connector_id: `c${number}`, charge_point_code: 'CP-01', connector_number: number, rated_kw: '22', confirmed_w: 0, reserved_w: 0, desired_w: 0, baseline_verified: false, status: 'Available' })),
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('saves with the advanced version after an own control action', async () => {
  let current = { ...snapshot, zero_limit_verified: true, offline_retention_verified: true, verification_note: 'Verified device' }
  const versions: number[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
    if (url.includes('/enable')) { current = { ...current, version: 2, enabled: true, state: 'ready' }; return new Response(JSON.stringify(current)) }
    if (options.method === 'PUT') { versions.push(JSON.parse(String(options.body)).version); return new Response(JSON.stringify(current)) }
    return new Response(JSON.stringify(url.includes('/power-config') ? current : { items: [{ id: 'station', name: 'Trạm thử' }], total_pages: 1 }))
  }))
  const user = userEvent.setup()
  render(<StationPowerPage />)
  await user.click(await screen.findByRole('button', { name: 'Bật chia tải' }))
  await screen.findByText('Đang chia tải')
  await user.click(screen.getByRole('button', { name: 'Lưu cấu hình' }))
  await waitFor(() => expect(versions).toEqual([2]))
})

it('retries the selected station and blocks stale station actions', async () => {
  let fail = true
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/station-b/')) return fail ? new Response(JSON.stringify({ detail: 'temporary' }), { status: 503 }) : new Response(JSON.stringify({ ...snapshot, station_id: 'station-b', limit_kw: '12' }))
    return new Response(JSON.stringify(url.includes('/power-config') ? snapshot : { items: [{ id: 'station', name: 'Trạm A' }, { id: 'station-b', name: 'Trạm B' }], total_pages: 1 }))
  }))
  const user = userEvent.setup()
  render(<StationPowerPage />)
  await screen.findByLabelText('Hạn mức tải sạc (kW)')
  await user.selectOptions(screen.getByLabelText('Trạm sạc'), 'station-b')
  await screen.findByRole('alert')
  expect(screen.queryByRole('button', { name: 'Lưu cấu hình' })).not.toBeInTheDocument()
  fail = false
  await user.click(screen.getByRole('button', { name: 'Tải lại' }))
  await waitFor(() => expect(screen.getByLabelText('Hạn mức tải sạc (kW)')).toHaveValue(12))
  expect(screen.getByLabelText('Trạm sạc')).toHaveValue('station-b')
})

it('ignores a poll started before a save and displays saved requests separately', async () => {
  let release: ((value: Response) => void) | undefined
  let reads = 0
  let poll: (() => void) | undefined
  vi.spyOn(window, 'setInterval').mockImplementation(callback => { poll = callback as () => void; return 1 })
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
    if (!url.includes('/power-config')) return new Response(JSON.stringify({ items: [{ id: 'station', name: 'Trạm thử' }], total_pages: 1 }))
    if (options.method === 'PUT') return new Response(JSON.stringify({ ...snapshot, version: 2, enabled: true, state: 'applying', limit_kw: '15' }))
    if (++reads === 2) return new Promise<Response>(resolve => { release = resolve })
    return new Response(JSON.stringify(snapshot))
  }))
  const user = userEvent.setup()
  render(<StationPowerPage />)
  await screen.findByText('Hạn mức đã lưu: 30 kW')
  const limit = screen.getByLabelText('Hạn mức tải sạc (kW)')
  await user.clear(limit); await user.type(limit, '15')
  expect(screen.getByText('Hạn mức đã lưu: 30 kW')).toBeInTheDocument()
  await act(async () => { poll?.() })
  await user.click(screen.getByRole('button', { name: 'Lưu cấu hình' }))
  await screen.findByText('Đang cập nhật giới hạn')
  await act(async () => { release?.(new Response(JSON.stringify(snapshot))) })
  expect(screen.getByText('Đang cập nhật giới hạn')).toBeInTheDocument()
  expect(screen.getByText('Hạn mức đã lưu: 15 kW')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Lưu cấu hình' })).toBeDisabled()
})

it('saves all connector ratings with version and only enables after saved commissioning evidence', async () => {
  const calls: { url: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
    if (url.includes('/power-config')) {
      if (options.method === 'PUT') {
        const body = JSON.parse(String(options.body))
        calls.push({ url, body })
        return new Response(JSON.stringify({ ...snapshot, version: 2, zero_limit_verified: true, offline_retention_verified: true, verification_note: body.verification_note }))
      }
      return new Response(JSON.stringify(snapshot))
    }
    if (url.includes('/enable')) {
      calls.push({ url, body: JSON.parse(String(options.body)) })
      return new Response(JSON.stringify({ ...snapshot, version: 3, enabled: true, state: 'bootstrap' }))
    }
    return new Response(JSON.stringify({ items: [{ id: 'station', name: 'Trạm thử' }], total_pages: 1 }))
  }))
  const user = userEvent.setup()
  render(<StationPowerPage />)
  await screen.findByText('Chưa bật chia tải')
  expect(screen.getByRole('button', { name: 'Bật chia tải' })).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: /Đã thử giới hạn 0 W/ }))
  await user.click(screen.getByRole('checkbox', { name: /Đã thử mất mạng/ }))
  await user.type(screen.getByLabelText('Ghi nhận thiết bị, firmware và kết quả thử'), 'Simulator G1 verified')
  await user.click(screen.getByRole('button', { name: 'Lưu cấu hình' }))
  await waitFor(() => expect(calls).toHaveLength(1))
  expect(calls[0].body).toMatchObject({ version: 1, limit_kw: '30', connectors: [{ connector_id: 'c1', rated_kw: '22' }, { connector_id: 'c2', rated_kw: '22' }, { connector_id: 'c3', rated_kw: '22' }] })
  await user.click(screen.getByRole('button', { name: 'Bật chia tải' }))
  await screen.findByText('Đang xác minh trụ')
  expect(calls[1].body).toEqual({ version: 2 })
  expect(screen.getByRole('button', { name: 'Lưu cấu hình' })).toBeDisabled()
})

it('keeps entered values when the server rejects a stale version', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
    if (options.method === 'PUT') return new Response(JSON.stringify({ detail: 'power_version_conflict' }), { status: 409 })
    return new Response(JSON.stringify(url.includes('/power-config') ? snapshot : { items: [{ id: 'station', name: 'Trạm thử' }], total_pages: 1 }))
  }))
  const user = userEvent.setup()
  render(<StationPowerPage />)
  const limit = await screen.findByLabelText('Hạn mức tải sạc (kW)')
  await user.clear(limit); await user.type(limit, '25')
  await user.click(screen.getByRole('button', { name: 'Lưu cấu hình' }))
  await screen.findByText(/Cấu hình đã được thay đổi/)
  expect(limit).toHaveValue(25)
})

it('shows retained offline budgets and an incomplete commissioning state', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/power-config') ? { ...snapshot, enabled: true, state: 'degraded', issue: 'offline_budget_retained' } : { items: [{ id: 'station', name: 'Trạm thử' }], total_pages: 1 }))))
  render(<StationPowerPage />)
  await screen.findByText(/Phần công suất đã cấp vẫn được giữ/)
  expect(screen.getByRole('button', { name: 'Kiểm tra lại chia tải' })).toBeDisabled()
})
