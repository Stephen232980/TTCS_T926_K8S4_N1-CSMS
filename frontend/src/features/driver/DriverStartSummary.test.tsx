import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DriverStartSummary } from './DriverStartSummary'

afterEach(() => vi.unstubAllGlobals())
const pricing = { energy_rate_vnd_per_kwh: 3000, idle_rate_vnd_per_minute: 500, grace_minutes: 2 }
const wallet = { balance: '882432', currency: 'VND', status: 'active' }

it('shows supplied prices and the server wallet without claiming eligibility', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => wallet })
  vi.stubGlobal('fetch', fetchMock)
  render(<DriverStartSummary pricing={pricing} />)
  expect(screen.getByText('3.000 đ/kWh')).toBeInTheDocument()
  expect(screen.getByText('500 đ/phút')).toBeInTheDocument()
  expect(screen.getByText('Miễn 2 phút')).toBeInTheDocument()
  expect(await screen.findByText('882.432 đ')).toBeInTheDocument()
  expect(screen.getByText('Giá lúc chọn trạm. Hệ thống kiểm tra số dư khi bắt đầu sạc.')).toBeInTheDocument()
  expect(screen.queryByText(/đủ điều kiện|tối thiểu/i)).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/v1\/driver\/wallet$/), expect.objectContaining({ credentials: 'include', signal: expect.any(AbortSignal) }))
})

it('keeps zero fees distinct from missing prices', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => wallet }))
  const view = render(<DriverStartSummary pricing={{ energy_rate_vnd_per_kwh: 0, idle_rate_vnd_per_minute: 0, grace_minutes: 0 }} />)
  expect(screen.getByText('0 đ/kWh')).toBeInTheDocument()
  expect(screen.getByText('0 đ/phút')).toBeInTheDocument()
  expect(screen.getByText('Miễn 0 phút')).toBeInTheDocument()
  await screen.findByText('882.432 đ')
  view.rerender(<DriverStartSummary pricing={{ energy_rate_vnd_per_kwh: null, idle_rate_vnd_per_minute: null }} />)
  expect(screen.getByText('Chưa có giá')).toBeInTheDocument()
  expect(screen.getByText('Chưa có thông tin')).toBeInTheDocument()
  expect(screen.queryByText('0 đ/kWh')).not.toBeInTheDocument()
})

it.each([
  [{ ...wallet, status: 'locked' }, 'Ví chưa hoạt động.', 'Kiểm tra ví'],
  [{ ...wallet, balance: '-5000' }, 'Ví đang có số dư âm.', 'Nạp tiền'],
])('explains a wallet restriction without authorizing a start', async (data, message, link) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => data }))
  render(<DriverStartSummary pricing={pricing} />)
  expect(await screen.findByText(message, { exact: false })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: link })).toHaveAttribute('href', '#driver-wallet')
})

it('recovers from an unreadable wallet when the driver returns to the page', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ balance: 'not money', currency: 'VND', status: 'active' }) })
    .mockResolvedValue({ ok: true, json: async () => wallet })
  vi.stubGlobal('fetch', fetchMock)
  render(<DriverStartSummary pricing={pricing} />)
  expect(await screen.findByText('Chưa tải được')).toBeInTheDocument()
  fireEvent(document, new Event('visibilitychange'))
  expect(await screen.findByText('882.432 đ')).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByText('Chưa tải được')).not.toBeInTheDocument())
  expect(fetchMock).toHaveBeenCalledTimes(2)
})
