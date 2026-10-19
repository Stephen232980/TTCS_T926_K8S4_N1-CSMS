import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { executePrivacyRequest, fetchPrivacyRequests, reviewPrivacyRequest } from './privacyApi'
import { PrivacyRequestReview } from './PrivacyRequestReview'

vi.mock('./privacyApi', () => ({ DEFAULT_PRIVACY_POLICY_VERSION: 'CSMS-PRIVACY-2026-01', executePrivacyRequest: vi.fn(), fetchPrivacyRequests: vi.fn(), reviewPrivacyRequest: vi.fn() }))

it('requires reason and policy version, and keeps approved execution blocked', async () => {
  const user = userEvent.setup()
  const receipt = { id: 'request-1', user_id: 'driver-1', status: 'pending' as const, reason: 'Request',
    created_at: '', reviewed_at: null, decision_reason: null, policy_version: null,
    execution_status: 'blocked' as const, blockers: ['privacy_execution_unavailable'] }
  vi.mocked(fetchPrivacyRequests).mockResolvedValue([receipt])
  vi.mocked(reviewPrivacyRequest).mockResolvedValue({ ...receipt, status: 'approved', decision_reason: 'Reviewed', policy_version: 'v1' })
  render(<PrivacyRequestReview />)
  const approve = await screen.findByRole('button', { name: 'Duyệt yêu cầu' })
  expect(approve).toBeDisabled()
  await user.type(screen.getByLabelText('Lý do quyết định'), 'Reviewed')
  await user.clear(screen.getByLabelText('Chính sách đã phê duyệt'))
  await user.type(screen.getByLabelText('Chính sách đã phê duyệt'), 'v1')
  await user.click(approve)
  expect(reviewPrivacyRequest).toHaveBeenCalledWith('request-1', 'approved', 'Reviewed', 'v1')
  expect(await screen.findByText(/Trạng thái: Đã duyệt · Thực thi: bị chặn/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Duyệt yêu cầu' })).not.toBeInTheDocument()
})


it('keeps decision input scoped to its request and does not offer execution for queued jobs', async () => {
  const user = userEvent.setup()
  const base = { user_id: 'driver', reason: 'Request', created_at: '', reviewed_at: null, decision_reason: null, policy_version: null, blockers: [] }
  vi.mocked(fetchPrivacyRequests).mockResolvedValue([
    { ...base, id: 'one', status: 'pending', execution_status: 'blocked' },
    { ...base, id: 'two', status: 'pending', execution_status: 'blocked' },
    { ...base, id: 'three', status: 'approved', execution_status: 'queued' },
  ])
  render(<PrivacyRequestReview />)
  const reasons = await screen.findAllByLabelText('Lý do quyết định')
  await user.type(reasons[0], 'Duyệt riêng hồ sơ một')
  expect(reasons[1]).toHaveValue('')
  const second = screen.getByText('two').closest('details')!
  expect(within(second).getByRole('button', { name: 'Duyệt yêu cầu' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Thử lại xử lý' })).not.toBeInTheDocument()
})


it('allows refund retry with confirmation only and sends the displayed balance', async () => {
  const user = userEvent.setup()
  const receipt = { id: 'refund', user_id: 'driver', status: 'approved' as const, reason: 'Request',
    created_at: '', reviewed_at: null, decision_reason: 'Approved', policy_version: 'v1',
    execution_status: 'needs_review' as const, blockers: ['refund_required'], wallet_balance_vnd: 495 }
  vi.mocked(fetchPrivacyRequests).mockResolvedValue([receipt])
  vi.mocked(executePrivacyRequest).mockResolvedValue({ ...receipt, execution_status: 'queued', blockers: [], wallet_balance_vnd: 0 })
  render(<PrivacyRequestReview />)
  const label = await screen.findByText(/Tôi xác nhận đã hoàn 495đ bên ngoài/)
  await user.click(screen.getByText('refund').closest('details')!.querySelector('summary')!)
  const retry = screen.getByRole('button', { name: 'Thử lại xử lý' })
  expect(retry).toBeDisabled()
  await user.click(label)
  expect(retry).toBeEnabled()
  await user.click(retry)
  expect(executePrivacyRequest).toHaveBeenCalledWith('refund', expect.any(String), 'EXECUTE_PRIVACY_REQUEST', {
    external_refund_confirmed: true, expected_balance_vnd: 495,
  })
})

it('keeps other obligations blocked even after refund confirmation', async () => {
  const user = userEvent.setup()
  vi.mocked(fetchPrivacyRequests).mockResolvedValue([{ id: 'held', user_id: 'driver', status: 'approved', reason: 'Request',
    created_at: '', reviewed_at: null, decision_reason: 'Approved', policy_version: 'v1',
    execution_status: 'needs_review', blockers: ['refund_required', 'legal_hold_or_unsettled_charging'], wallet_balance_vnd: 495 }])
  render(<PrivacyRequestReview />)
  const label = await screen.findByText(/Tôi xác nhận đã hoàn 495đ bên ngoài/)
  await user.click(screen.getByText('held').closest('details')!.querySelector('summary')!)
  await user.click(label)
  expect(screen.getByRole('button', { name: 'Thử lại xử lý' })).toBeDisabled()
})
