import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { adminRequest } from '../admin/adminApi'
import { DriverPrivacy } from './DriverPrivacy'

vi.mock('../admin/adminApi', () => ({ adminRequest: vi.fn(), writeJson: (method: string, payload: unknown) => ({ method, body: JSON.stringify(payload) }) }))

beforeEach(() => vi.resetAllMocks())

it('submits reauthentication, shows a receipt and clears the password', async () => {
  const user = userEvent.setup()
  vi.mocked(adminRequest).mockResolvedValueOnce([]).mockResolvedValueOnce({
    id: 'request-1', status: 'pending', blockers: ['refund_required'],
  })
  render(<DriverPrivacy />)
  const password = await screen.findByLabelText(/Mật khẩu hiện tại/)
  await user.type(password, 'reauth-password')
  await user.click(screen.getByRole('button', { name: 'Gửi yêu cầu' }))
  expect(await screen.findByText('Yêu cầu request-1')).toBeInTheDocument()
  expect(screen.getByText('Chờ duyệt')).toBeInTheDocument()
  expect(screen.getByText(/Cần xử lý hoàn tiền/)).toBeInTheDocument()
  expect(screen.queryByLabelText(/Mật khẩu hiện tại/)).not.toBeInTheDocument()
  expect(adminRequest).toHaveBeenLastCalledWith('/driver/privacy/anonymize-request', {
    method: 'POST', body: JSON.stringify({ current_password: 'reauth-password', reason: null }),
  })
})

it('restores the saved request on reload without showing deletion success', async () => {
  vi.mocked(adminRequest).mockResolvedValueOnce([{
    id: 'saved-request', status: 'approved', decision_reason: 'Đã xét yêu cầu', policy_version: 'v1',
    blockers: ['debt_resolution_required'],
  }])
  render(<DriverPrivacy />)
  expect(await screen.findByText('Yêu cầu saved-request')).toBeInTheDocument()
  expect(screen.getByText('Đã duyệt, chưa thực thi')).toBeInTheDocument()
  expect(screen.getByText(/Cần xử lý khoản nợ/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Gửi yêu cầu' })).not.toBeInTheDocument()
})
