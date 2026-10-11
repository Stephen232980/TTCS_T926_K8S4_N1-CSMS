import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ControlAction } from './ControlAction'
import { ControlAudit } from './ControlAudit'

afterEach(() => vi.unstubAllGlobals())
const reply = (status: string) => ({ ok: true, json: async () => ({ id: 'request', status }) })

it('confirms soft reset and submits only once while waiting', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn().mockResolvedValue(reply('Accepted'))
  vi.stubGlobal('fetch', fetchMock)
  render(<ControlAction chargerId="charger" label="CP-01" />)
  await user.click(screen.getByRole('button', { name: 'Khởi động lại CP-01' }))
  expect(screen.getByLabelText('Kiểu khởi động')).toHaveValue('Soft')
  await user.click(screen.getByRole('button', { name: 'Xác nhận gửi lệnh' }))
  expect(await screen.findByText('Trụ đã chấp nhận lệnh.')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(1)
  const body = JSON.parse(fetchMock.mock.calls[0][1].body)
  expect(body.type).toBe('Soft')
  expect(body.request_id).toMatch(/^[a-f0-9-]{36}$/)
  expect(screen.getByRole('button', { name: 'Xác nhận gửi lệnh' })).toBeDisabled()
})

it('keeps a remotely stopped session open after Accepted', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply('Accepted')))
  const user = userEvent.setup()
  render(<ControlAction sessionId={42} label="phiên 42" />)
  await user.click(screen.getByRole('button', { name: 'Dừng từ xa phiên 42' }))
  await user.click(screen.getByRole('button', { name: 'Xác nhận gửi lệnh' }))
  expect(await screen.findByText(/Phiên vẫn mở cho đến khi trụ gửi tin kết thúc/)).toBeInTheDocument()
})

it.each(['Rejected', 'Offline', 'Timeout', 'Disconnected'])('shows actionable %s result', async status => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(status)))
  const user = userEvent.setup()
  render(<ControlAction sessionId={42} label="phiên 42" />)
  await user.click(screen.getByRole('button', { name: 'Dừng từ xa phiên 42' }))
  await user.click(screen.getByRole('button', { name: 'Xác nhận gửi lệnh' }))
  expect(await screen.findByRole('alert')).toBeInTheDocument()
})

it('reuses the same request key after a network error', async () => {
  const fetchMock = vi.fn().mockRejectedValueOnce(new Error('Mất mạng')).mockResolvedValue(reply('Accepted'))
  vi.stubGlobal('fetch', fetchMock)
  const user = userEvent.setup()
  render(<ControlAction chargerId="charger" label="CP-01" />)
  await user.click(screen.getByRole('button', { name: 'Khởi động lại CP-01' }))
  await user.click(screen.getByRole('button', { name: 'Xác nhận gửi lệnh' }))
  await screen.findByRole('alert')
  await user.click(screen.getByRole('button', { name: 'Kiểm tra lại yêu cầu' }))
  await screen.findByText('Trụ đã chấp nhận lệnh.')
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).request_id).toBe(JSON.parse(fetchMock.mock.calls[1][1].body).request_id)
})

it('filters audit by charger, actor and a date range', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0, page: 1, total_pages: 1 }) })
  vi.stubGlobal('fetch', fetchMock)
  const user = userEvent.setup()
  render(<ControlAudit />)
  await screen.findByText('Chưa có lệnh phù hợp với bộ lọc.')
  await user.type(screen.getByLabelText('Mã trụ'), 'CP-01')
  await user.type(screen.getByLabelText('Email người thực hiện'), 'operator@example.com')
  await user.click(screen.getByRole('button', { name: 'Lọc nhật ký' }))
  await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining('charge_point_code=CP-01&actor_email=operator%40example.com'), expect.anything()))
})
