import { useEffect, useState } from 'react'
import { dateTime, numberText } from './adminApi'
import { ErrorNotice } from './AdminShared'
import { PrivacyRequestReview } from './PrivacyRequestReview'
import {
  fetchLegalHold,
  fetchRetentionPolicies,
  submitLegalHold,
  triggerRetentionCleanup,
  type LegalHoldResponse,
  type RetentionCleanupResponse,
  type RetentionPoliciesResponse,
} from './privacyApi'

export function AdminPrivacyRetention() {
  const [policiesData, setPoliciesData] = useState<RetentionPoliciesResponse | null>(null)
  const [loadingPolicies, setLoadingPolicies] = useState(true)
  const [policiesError, setPoliciesError] = useState<unknown>(null)

  // Cleanup state
  const [cleaning, setCleaning] = useState(false)
  const [cleanupResult, setCleanupResult] = useState<RetentionCleanupResponse | null>(null)
  const [cleanupError, setCleanupError] = useState<unknown>(null)
  const [showCleanupConfirm, setShowCleanupConfirm] = useState(false)

  // Legal hold state
  const [holdUserId, setHoldUserId] = useState('')
  const [holdQueryLoading, setHoldQueryLoading] = useState(false)
  const [holdQueryResult, setHoldQueryResult] = useState<LegalHoldResponse | null>(null)
  const [holdQueryError, setHoldQueryError] = useState<unknown>(null)

  const [holdReason, setHoldReason] = useState('')
  const [holdActionLoading, setHoldActionLoading] = useState(false)
  const [holdActionMessage, setHoldActionMessage] = useState('')
  const [holdActionError, setHoldActionError] = useState<unknown>(null)

  const loadPolicies = async (signal?: AbortSignal) => {
    setLoadingPolicies(true)
    setPoliciesError(null)
    try {
      const data = await fetchRetentionPolicies(signal)
      if (!signal?.aborted) setPoliciesData(data)
    } catch (err) {
      if (!signal?.aborted) setPoliciesError(err)
    } finally {
      if (!signal?.aborted) setLoadingPolicies(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    void fetchRetentionPolicies(controller.signal).then(data => {
      if (!controller.signal.aborted) setPoliciesData(data)
    }).catch(err => {
      if (!controller.signal.aborted) setPoliciesError(err)
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingPolicies(false)
    })
    return () => controller.abort()
  }, [])

  const handleRunCleanup = async () => {
    setCleaning(true)
    setCleanupError(null)
    setCleanupResult(null)
    try {
      const res = await triggerRetentionCleanup()
      setCleanupResult(res)
      setShowCleanupConfirm(false)
      loadPolicies()
    } catch (err) {
      setCleanupError(err)
    } finally {
      setCleaning(false)
    }
  }

  const handleCheckLegalHold = async () => {
    if (!holdUserId.trim()) return
    setHoldQueryLoading(true)
    setHoldQueryError(null)
    setHoldQueryResult(null)
    setHoldActionMessage('')
    try {
      const res = await fetchLegalHold(holdUserId.trim())
      setHoldQueryResult(res)
    } catch (err) {
      setHoldQueryError(err)
    } finally {
      setHoldQueryLoading(false)
    }
  }

  const handleToggleLegalHold = async (newHoldState: boolean) => {
    if (!holdUserId.trim() || !holdReason.trim()) return
    setHoldActionLoading(true)
    setHoldActionError(null)
    setHoldActionMessage('')
    try {
      const res = await submitLegalHold(holdUserId.trim(), newHoldState, holdReason.trim())
      setHoldQueryResult(res)
      setHoldActionMessage(
        newHoldState
          ? 'Đã áp dụng tạm giữ pháp lý cho tài khoản.'
          : 'Đã gỡ bỏ tạm giữ pháp lý cho tài khoản.'
      )
      setHoldReason('')
    } catch (err) {
      setHoldActionError(err)
    } finally {
      setHoldActionLoading(false)
    }
  }

  return (
    <div className="admin-privacy-container">
      <header className="admin-page-header">
        <div>
          <h1>Lưu trữ dữ liệu & Quyền riêng tư</h1>
          <p className="admin-page-description">
            Xem chính sách lưu trữ, quản lý tạm giữ và duyệt yêu cầu dữ liệu cá nhân.
            Thực thi theo policy CSMS-PRIVACY-2026-01 sau khi kiểm tra hồ sơ và hạ tầng phục hồi.
          </p>
        </div>
      </header>

      {/* SECTION 1: Retention Policies & On-demand Cleanup */}
      <section className="admin-section" aria-labelledby="retention-policies-title">
        <div className="admin-section-header">
          <div>
            <h2 id="retention-policies-title">Chính sách lưu trữ dữ liệu tạm thời</h2>
            {policiesData && (
              <p className="admin-section-meta">
                Lần kiểm tra gần nhất: {dateTime(policiesData.checked_at)} · Chu kỳ dọn tự động:{' '}
                {numberText(policiesData.auto_cleanup_interval_seconds)} giây
              </p>
            )}
          </div>
          <div className="admin-actions">
            <button
              type="button"
              className="admin-button secondary"
              onClick={() => loadPolicies()}
              disabled={loadingPolicies}
            >
              {loadingPolicies ? 'Đang tải…' : 'Làm mới'}
            </button>
            <button
              type="button"
              className="admin-button primary"
              onClick={() => setShowCleanupConfirm(true)}
              disabled={cleaning || !policiesData?.cleanup_enabled}
            >
              {cleaning ? 'Đang dọn dẹp…' : 'Chạy dọn dẹp ngay'}
            </button>
          </div>
        </div>

        {policiesData?.blocked_reason && <p role="status">{policiesData.blocked_reason}. Chưa xóa bản ghi nào.</p>}
        <ErrorNotice error={policiesError} onRetry={() => loadPolicies()} />

        {/* Cleanup Result Banner */}
        {cleanupResult && (
          <div className="admin-banner success" role="status">
            <h3>{cleanupResult.status === 'completed' ? 'Đã dọn dẹp theo policy' : 'Dọn dẹp bị chặn'}</h3>
            <p>
              Thời gian thực hiện: {dateTime(cleanupResult.executed_at)} ·{' '}
              <strong>Tổng số bản ghi đã xóa an toàn: {numberText(cleanupResult.total_deleted)}</strong>
            </p>
            <ul>
              <li>Bản ghi đăng nhập sai: {numberText(cleanupResult.deleted_login_attempts)}</li>
              <li>Phiên web đã thu hồi: {numberText(cleanupResult.deleted_expired_sessions)}</li>
              <li>Khóa tạo trạm idempotency: {numberText(cleanupResult.deleted_idempotency_keys)}</li>
              <li>Tin nhắn OCPP chờ mồ côi: {numberText(cleanupResult.deleted_pending_messages)}</li>
              <li>Mẫu telemetry quá hạn: {numberText(cleanupResult.deleted_telemetry_buckets)}</li>
              <li>Email cảnh báo đã gửi: {numberText(cleanupResult.deleted_sent_alert_emails)}</li>
              <li>Mẫu sức khỏe quá hạn: {numberText(cleanupResult.deleted_health_samples)}</li>
            </ul>
          </div>
        )}

        <ErrorNotice error={cleanupError} />

        {/* Confirmation Modal */}
        {showCleanupConfirm && (
          <div className="admin-confirm-dialog" role="dialog" aria-modal="true">
            <div className="admin-dialog-content">
              <h3>Xác nhận thực hiện dọn dẹp dữ liệu</h3>
              <p>
                Thao tác này sẽ xóa vĩnh viễn các bản ghi tạm thời đã quá hạn lưu trữ theo chính sách
                cấu hình hệ thống (nhật ký khóa IP cũ, phiên đăng nhập đã hủy, telemetry cũ, email
                thông báo đã gửi).
              </p>
              <p>
                <strong>Lưu ý:</strong> Hóa đơn, giao dịch ví tiền và lịch sử phiên sạc sẽ{' '}
                <em>không bao giờ</em> bị ảnh hưởng.
              </p>
              <div className="admin-dialog-actions">
                <button
                  type="button"
                  className="admin-button secondary"
                  onClick={() => setShowCleanupConfirm(false)}
                  disabled={cleaning}
                >
                  Hủy bỏ
                </button>
                <button
                  type="button"
                  className="admin-button danger"
                  onClick={handleRunCleanup}
                  disabled={cleaning}
                >
                  {cleaning ? 'Đang thực hiện…' : 'Xác nhận dọn dẹp'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Policies Table */}
        <div className="admin-table-container">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Bảng dữ liệu</th>
                <th>Phân loại</th>
                <th>Thời hạn lưu trữ</th>
                <th>Mô tả dọn dẹp</th>
                <th style={{ textAlign: 'right' }}>Ứng viên theo ngưỡng</th>
              </tr>
            </thead>
            <tbody>
              {policiesData?.policies.map((policy) => (
                <tr key={policy.table_name}>
                  <td>
                    <code>{policy.table_name}</code>
                  </td>
                  <td>{policy.policy_type}</td>
                  <td>
                    <span className="admin-badge info">{policy.retention_threshold}</span>
                  </td>
                  <td>{policy.description}</td>
                  <td style={{ textAlign: 'right', fontWeight: 600 }}>
                    {numberText(policy.eligible_count)}
                  </td>
                </tr>
              ))}
              {!policiesData && loadingPolicies && (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '32px' }}>
                    Đang tải danh sách chính sách lưu trữ…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* SECTION 2: Legal Hold and Account Protection */}
      <section className="admin-section" aria-labelledby="legal-hold-title">
        <div className="admin-section-header">
          <div>
            <h2 id="legal-hold-title">Tạm giữ pháp lý (Legal Hold)</h2>
            <p className="admin-section-meta">
              Bảo vệ tài khoản đang có tranh chấp pháp lý hoặc kiểm toán. Tài khoản bị tạm giữ sẽ
              không thể bị ẩn danh hoặc xóa dữ liệu.
            </p>
          </div>
        </div>

        <div className="admin-card">
          <div className="admin-search-form" style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
            <input
              type="text"
              placeholder="Nhập User ID (UUID) cần tra cứu tạm giữ…"
              value={holdUserId}
              onChange={(e) => setHoldUserId(e.target.value)}
              style={{ flex: 1 }}
            />
            <button
              type="button"
              className="admin-button secondary"
              onClick={handleCheckLegalHold}
              disabled={holdQueryLoading || !holdUserId.trim()}
            >
              {holdQueryLoading ? 'Đang kiểm tra…' : 'Tra cứu trạng thái'}
            </button>
          </div>

          <ErrorNotice error={holdQueryError} />

          {holdQueryResult && (
            <div className="admin-hold-status-card" style={{ padding: '16px', background: '#f8fafc', borderRadius: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
                <strong>Trạng thái tạm giữ:</strong>
                {holdQueryResult.legal_hold ? (
                  <span className="admin-badge warning" style={{ background: '#fef3c7', color: '#92400e', padding: '4px 8px', borderRadius: '4px' }}>
                    ĐANG TẠM GIỮ PHÁP LÝ
                  </span>
                ) : (
                  <span className="admin-badge success" style={{ background: '#dcfce7', color: '#166534', padding: '4px 8px', borderRadius: '4px' }}>
                    BÌNH THƯỜNG (KHÔNG TẠM GIỮ)
                  </span>
                )}
              </div>
              {holdQueryResult.reason && (
                <p style={{ margin: '8px 0' }}>
                  <strong>Lý do:</strong> {holdQueryResult.reason}
                </p>
              )}
              <p style={{ margin: '8px 0', fontSize: '0.85rem', color: '#64748b' }}>
                Cập nhật lúc: {dateTime(holdQueryResult.updated_at)}
              </p>

              {/* Action Form */}
              <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #e2e8f0' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>
                  Lý do thay đổi tạm giữ (bắt buộc):
                </label>
                <input
                  type="text"
                  placeholder="Nhập lý do tạm giữ hoặc lý do giải tỏa…"
                  value={holdReason}
                  onChange={(e) => setHoldReason(e.target.value)}
                  style={{ width: '100%', marginBottom: '12px' }}
                />
                <div style={{ display: 'flex', gap: '8px' }}>
                  {holdQueryResult.legal_hold ? (
                    <button
                      type="button"
                      className="admin-button secondary"
                      onClick={() => handleToggleLegalHold(false)}
                      disabled={holdActionLoading || !holdReason.trim()}
                    >
                      {holdActionLoading ? 'Đang xử lý…' : 'Gỡ bỏ tạm giữ pháp lý'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="admin-button warning"
                      onClick={() => handleToggleLegalHold(true)}
                      disabled={holdActionLoading || !holdReason.trim()}
                    >
                      {holdActionLoading ? 'Đang xử lý…' : 'Áp dụng tạm giữ pháp lý'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {holdActionMessage && (
            <div className="admin-banner success" style={{ marginTop: '12px' }}>
              {holdActionMessage}
            </div>
          )}
          <ErrorNotice error={holdActionError} />
        </div>
      </section>

      <PrivacyRequestReview />
    </div>
  )
}
