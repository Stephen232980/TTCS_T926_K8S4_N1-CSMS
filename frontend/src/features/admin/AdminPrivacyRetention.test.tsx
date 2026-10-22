import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { AdminPrivacyRetention } from './AdminPrivacyRetention'
import { fetchPrivacyRequests, fetchRetentionPolicies, fetchLegalHold } from './privacyApi'
vi.mock('./privacyApi', () => ({ DEFAULT_PRIVACY_POLICY_VERSION: 'CSMS-PRIVACY-2026-01', fetchPrivacyRequests: vi.fn(), fetchRetentionPolicies: vi.fn(), fetchLegalHold: vi.fn() }))
it('shows the original privacy request flow without technical cleanup or standalone hold tools', async () => {
  vi.mocked(fetchPrivacyRequests).mockResolvedValue([])
  render(<AdminPrivacyRetention />)
  expect(await screen.findByText('Chưa có yêu cầu.')).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Lưu trữ & quyền riêng tư')
  expect(screen.queryByText('Chạy dọn dẹp ngay')).not.toBeInTheDocument()
  expect(screen.queryByPlaceholderText(/UUID/)).not.toBeInTheDocument()
  expect(fetchRetentionPolicies).not.toHaveBeenCalled()
  expect(fetchLegalHold).not.toHaveBeenCalled()
})
