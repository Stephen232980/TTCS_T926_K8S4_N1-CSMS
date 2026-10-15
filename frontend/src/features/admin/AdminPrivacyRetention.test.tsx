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
  submitAnonymizeUser: vi.fn(),
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
  checked_at: '2026-10-15T00:00:00Z',
}

describe('AdminPrivacyRetention', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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

  it('executes retention cleanup upon confirmation and renders result banner', async () => {
    const user = userEvent.setup()
    const mockCleanupResult: privacyApi.RetentionCleanupResponse = {
      executed_at: '2026-10-15T01:00:00Z',
      deleted_login_attempts: 5,
      deleted_expired_sessions: 3,
      deleted_idempotency_keys: 1,
      deleted_pending_messages: 0,
      deleted_telemetry_buckets: 10,
      deleted_sent_alert_emails: 2,
      deleted_health_samples: 4,
      total_deleted: 25,
    }
    vi.mocked(privacyApi.triggerRetentionCleanup).mockResolvedValue(mockCleanupResult)

    render(<AdminPrivacyRetention />)
    await screen.findByText('login_ip_attempts')

    // Click trigger cleanup button
    const cleanupBtn = screen.getByRole('button', { name: 'Chạy dọn dẹp ngay' })
    await user.click(cleanupBtn)

    // Modal appears
    expect(screen.getByText('Xác nhận thực hiện dọn dẹp dữ liệu')).toBeInTheDocument()

    // Confirm cleanup
    const confirmBtn = screen.getByRole('button', { name: 'Xác nhận dọn dẹp' })
    await user.click(confirmBtn)

    await waitFor(() => {
      expect(screen.getByText('Dọn dẹp dữ liệu hoàn tất!')).toBeInTheDocument()
      expect(screen.getByText(/Tổng số bản ghi đã xóa an toàn: 25/)).toBeInTheDocument()
    })
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

  it('submits soft anonymization and shows preserved financial records', async () => {
    const user = userEvent.setup()
    const testUserId = '99999999-8888-7777-6666-555555555555'

    vi.mocked(privacyApi.submitAnonymizeUser).mockResolvedValue({
      user_id: testUserId,
      anonymized_email: 'anonymized_999999998888@deleted.local',
      status: 'anonymized',
      anonymized_at: '2026-10-15T02:00:00Z',
      preserved_financial_records: {
        invoices: 10,
        charging_sessions: 6,
        wallet_ledger_entries: 14,
      },
    })

    render(<AdminPrivacyRetention />)

    const idInput = screen.getByPlaceholderText(/ví dụ: a1b2c3d4/)
    await user.type(idInput, testUserId)

    const reasonInput = screen.getByPlaceholderText(/Nhập lý do ẩn danh hóa/)
    await user.type(reasonInput, 'Yêu cầu của người dùng')

    const confirmInput = screen.getByPlaceholderText('CONFIRM_ANONYMIZE')
    await user.type(confirmInput, 'CONFIRM_ANONYMIZE')

    const submitBtn = screen.getByRole('button', { name: 'Xác nhận ẩn danh hóa tài khoản' })
    expect(submitBtn).not.toBeDisabled()

    await user.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByText('Ẩn danh hóa tài khoản thành công!')).toBeInTheDocument()
      expect(screen.getByText('anonymized_999999998888@deleted.local')).toBeInTheDocument()
      expect(screen.getByText(/Hóa đơn: 10/)).toBeInTheDocument()
      expect(screen.getByText(/Phiên sạc: 6/)).toBeInTheDocument()
      expect(screen.getByText(/Giao dịch sổ cái ví: 14/)).toBeInTheDocument()
    })
  })
})
