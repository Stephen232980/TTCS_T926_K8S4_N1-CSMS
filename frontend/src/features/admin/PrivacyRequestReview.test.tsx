import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { fetchPrivacyRequests, reviewPrivacyRequest } from './privacyApi'
import { PrivacyRequestReview } from './PrivacyRequestReview'

vi.mock('./privacyApi', () => ({ fetchPrivacyRequests: vi.fn(), reviewPrivacyRequest: vi.fn() }))

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
  await user.type(screen.getByLabelText('Phiên bản policy đã phê duyệt'), 'v1')
  await user.click(approve)
  expect(reviewPrivacyRequest).toHaveBeenCalledWith('request-1', 'approved', 'Reviewed', 'v1')
  expect(await screen.findByText(/Trạng thái: Đã duyệt · Thực thi: bị chặn/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Duyệt yêu cầu' })).not.toBeInTheDocument()
})
