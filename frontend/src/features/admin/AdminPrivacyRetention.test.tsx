import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminPrivacyRetention } from './AdminPrivacyRetention'
import * as privacyApi from './privacyApi'

vi.mock('./privacyApi', () => ({
  fetchRetentionPolicies: vi.fn(),
  triggerRetentionCleanup: vi.fn(),
  fetchLegalHold: vi.fn(),
  submitLegalHold: vi.fn(),
  fetchPrivacyRequests: vi.fn(),
  reviewPrivacyRequest: vi.fn(),
}))

const mockPolicies: privacyApi.RetentionPoliciesResponse = {
  policies: [
    {
      table_name: 'login_ip_attempts',
      policy_type: 'Khóa IP',
      retention_threshold: '30 ngày',
      description: 'Dọn đăng nhập sai',
      eligible_count: 5,
    },
    {
      table_name: 'sessions',
      policy_type: 'Phiên web',
      retention_threshold: '7 ngày',
      description: 'Phiên đã thu hồi',
      eligible_count: 3,
    },
  ],
  auto_cleanup_interval_seconds: 86400,
  cleanup_enabled: false,
  blocked_reason: "Chưa có policy được phê duyệt",
  checked_at: '2026-10-15T00:00:00Z',
}

describe('AdminPrivacyRetention', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(privacyApi.fetchPrivacyRequests).mockResolvedValue([])
    vi.mocked(privacyApi.fetchRetentionPolicies).mockResolvedValue(mockPolicies)
  })

  it('renders retention policies table and auto-cleanup interval', async () => {
    render(<AdminPrivacyRetention />)

    expect(screen.getByText('Lưu trữ dữ liệu & Quyền riêng tư')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('login_ip_attempts')).toBeInTheDocument()
      expect(screen.getByText('sessions')).toBeInTheDocument()
    })
  })

  it('blocks cleanup and hides direct anonymization while dependencies are missing', async () => {
    render(<AdminPrivacyRetention />)
    await screen.findByText('login_ip_attempts')
    expect(screen.getByRole('button', { name: 'Chạy dọn dẹp ngay' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Xác nhận ẩn danh hóa tài khoản' })).not.toBeInTheDocument()
    expect(screen.getByText(/Chưa có policy được phê duyệt/)).toBeInTheDocument()
  })

  it('queries and toggles legal hold status', async () => {
    const user = userEvent.setup()
    const testUserId = '11111111-2222-3333-4444-555555555555'

    vi.mocked(privacyApi.fetchLegalHold).mockResolvedValue({
      user_id: testUserId,
      legal_hold: false,
      reason: null,
      updated_at: '2026-10-15T00:00:00Z',
    })

    vi.mocked(privacyApi.submitLegalHold).mockResolvedValue({
      user_id: testUserId,
      legal_hold: true,
      reason: 'Tranh chấp hóa đơn',
      updated_at: '2026-10-15T00:05:00Z',
    })

    render(<AdminPrivacyRetention />)

    const input = screen.getByPlaceholderText(/Nhập User ID/)
    await user.type(input, testUserId)

    const checkBtn = screen.getByRole('button', { name: 'Tra cứu trạng thái' })
    await user.click(checkBtn)

    await waitFor(() => {
      expect(screen.getByText('BÌNH THƯỜNG (KHÔNG TẠM GIỮ)')).toBeInTheDocument()
    })

    // Apply hold with reason
    const reasonInput = screen.getByPlaceholderText(/Nhập lý do tạm giữ/)
    await user.type(reasonInput, 'Tranh chấp hóa đơn')

    const applyHoldBtn = screen.getByRole('button', { name: 'Áp dụng tạm giữ pháp lý' })
    await user.click(applyHoldBtn)

    await waitFor(() => {
      expect(privacyApi.submitLegalHold).toHaveBeenCalledWith(testUserId, true, 'Tranh chấp hóa đơn')
      expect(screen.getByText('Đã áp dụng tạm giữ pháp lý cho tài khoản.')).toBeInTheDocument()
    })
  })

})
