import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { StationOperation } from './StationOperation'
import type { Station } from '../stations/model/station'

const station: Station = { id: 's1', name: 'Trạm thử', address: 'Test', latitude: 10.7, longitude: 106.7, status: 'active', statusVersion: 4, createdAt: '', updatedAt: '' }
afterEach(() => vi.unstubAllGlobals())

it('focuses the required reason, submits JSON with revision and reports session preservation', async () => {
  const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'suspended', status_version: 5 })))
  vi.stubGlobal('fetch', request)
  const changed = vi.fn(), user = userEvent.setup()
  render(<StationOperation station={station} onChanged={changed} onReload={vi.fn()} />)
  await user.click(screen.getByRole('button', { name: 'Tạm ngừng trạm' }))
  expect(screen.getByLabelText('Lý do tạm ngừng')).toHaveFocus()
  expect(screen.getByRole('button', { name: 'Xác nhận tạm ngừng' })).toBeDisabled()
  await user.type(screen.getByLabelText('Lý do tạm ngừng'), 'Bảo trì định kỳ')
  await user.click(screen.getByRole('button', { name: 'Xác nhận tạm ngừng' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Phiên đang chạy vẫn được kết thúc bình thường')
  expect(request).toHaveBeenCalledWith('/api/v1/owner/stations/s1/operation', expect.objectContaining({ method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'suspended', expected_version: 4, reason: 'Bảo trì định kỳ' }) }))
  expect(changed).toHaveBeenCalledWith('suspended', 5)
})

it('hides mutations for an admin blocked station', () => {
  render(<StationOperation station={{ ...station, status: 'blocked' }} onChanged={vi.fn()} onReload={vi.fn()} />)
  expect(screen.getByText(/Liên hệ quản trị viên/)).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('keeps the pending form on version conflict and offers reload instead of claiming success', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'station_version_conflict' }), { status: 409 })))
  const reload = vi.fn(), changed = vi.fn(), user = userEvent.setup()
  render(<StationOperation station={station} onChanged={changed} onReload={reload} />)
  await user.click(screen.getByRole('button', { name: 'Tạm ngừng trạm' }))
  await user.type(screen.getByLabelText('Lý do tạm ngừng'), 'Bảo trì')
  await user.click(screen.getByRole('button', { name: 'Xác nhận tạm ngừng' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Thông tin trạm đã thay đổi')
  expect(changed).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'Tải lại trạm' }))
  expect(reload).toHaveBeenCalledOnce()
})


it('cancels the modal without changing operation and restores the trigger focus', async () => {
  const request = vi.fn(); vi.stubGlobal('fetch', request)
  const user = userEvent.setup()
  render(<StationOperation station={station} onChanged={vi.fn()} onReload={vi.fn()} />)
  const trigger = screen.getByRole('button', { name: 'Tạm ngừng trạm' })
  await user.click(trigger)
  const modal = screen.getByRole('dialog', { name: 'Tạm ngừng Trạm thử' })
  await user.type(screen.getByLabelText('Lý do tạm ngừng'), 'Chưa xác nhận')
  fireEvent(modal, new Event('cancel', { cancelable: true }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  expect(request).not.toHaveBeenCalled()
})
