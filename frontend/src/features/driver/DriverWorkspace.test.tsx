import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DriverWorkspace } from './DriverWorkspace'

vi.mock('../../components/maps/StationMap', () => ({ StationMap: () => <div aria-label="Bản đồ trạm sạc" /> }))
afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

it('preserves station search across connector navigation and only calls driver endpoints', async () => {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes('/charging/current') ? { session: null, start_request: null } : url.includes('/connectors') ? { items: [{ id: 'connector', charge_point_code: 'TRU-01', connector_number: 1, status: 'Reserved' }] } : { items: [{ id: 'station', name: 'Trạm thật', address: 'Địa chỉ', latitude: 10.7, longitude: 106.7 }], page: 1, total: 1, total_pages: 1 } }))
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
  expect(reserved).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Bắt đầu sạc' })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'Quay lại bản đồ và danh sách' }))
  expect(screen.getByLabelText('Tên trạm hoặc địa chỉ')).toHaveValue('Trạm')
  await waitFor(() => expect(screen.getByRole('button', { name: /Trạm thật/ })).toHaveAttribute('aria-pressed', 'true'))
  expect(fetchMock.mock.calls.every(([url]) => url.includes('/api/v1/driver/'))).toBe(true)
  expect(fetchMock.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
})
