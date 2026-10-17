import { useEffect, useState } from 'react'
import { ErrorNotice } from './AdminShared'
import { fetchPrivacyRequests, reviewPrivacyRequest, type PrivacyReceipt, executePrivacyRequest, DEFAULT_PRIVACY_POLICY_VERSION } from './privacyApi'

const blockers: Record<string, string> = {
  privacy_execution_unavailable: 'Chưa hỗ trợ thực thi xóa dữ liệu',
  approved_data_class_policy_required: 'Cần chính sách được phê duyệt cho từng loại dữ liệu',
  subject_pii_separation_required: 'Cần tách định danh khỏi lịch sử vận hành',
  restricted_financial_retention_required: 'Cần giới hạn truy cập chứng từ phải lưu giữ',
  checkpoint_executor_and_restore_tombstones_required: 'Cần cơ chế phục hồi công việc và chống khôi phục lại dữ liệu đã xóa',
  approval_required: 'Chờ duyệt',
  request_rejected: 'Đã từ chối yêu cầu',
  legal_hold_or_unsettled_charging: 'Có tạm giữ hoặc phiên sạc chưa quyết toán',
  connector_release_required: 'Chưa xác nhận rút cáp',
  reservation_or_fee_pending: 'Đặt chỗ hoặc phí chưa xử lý xong',
  wallet_refund_or_debt_required: 'Cần hoàn tiền hoặc xử lý nợ trước khi thực thi',
  charging_or_cable_open: 'Phiên sạc/cáp hoặc quyết toán chưa hoàn tất',
  legal_hold: 'Đang có tạm giữ',
  execution_failed: 'Thực thi chưa hoàn tất; cần kiểm tra trước khi thử lại',
  refund_required: 'Cần hoàn tiền và đối chiếu chứng từ',
  debt_resolution_required: 'Cần xử lý khoản nợ',
}

export function PrivacyRequestReview() {
  const [requests, setRequests] = useState<PrivacyReceipt[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [reason, setReason] = useState('')
  const [policy, setPolicy] = useState(DEFAULT_PRIVACY_POLICY_VERSION)
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void fetchPrivacyRequests(controller.signal).then(data => {
      if (!controller.signal.aborted) setRequests(data)
    }).catch(err => {
      if (!controller.signal.aborted) setError(err)
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [])

  async function refresh() {
    setLoading(true)
    setError(null)
    try { setRequests(await fetchPrivacyRequests()) }
    catch (err) { setError(err) }
    finally { setLoading(false) }
  }

  async function decide(id: string, decision: 'approved' | 'rejected') {
    setBusy(true)
    setError(null)
    try {
      const receipt = await reviewPrivacyRequest(id, decision, reason.trim(), policy.trim())
      setRequests(rows => rows.map(row => row.id === id ? receipt : row))
      setReason('')
      setPolicy(DEFAULT_PRIVACY_POLICY_VERSION)
    } catch (err) { setError(err) }
    finally { setBusy(false) }
  }

  async function process(id: string) {
    setBusy(true)
    setError(null)
    try {
      const result = await executePrivacyRequest(id, reason.trim(), confirm)
      setRequests(rows => rows.map(row => row.id === id ? result : row))
      setConfirm('')
    } catch (err) { setError(err) }
    finally { setBusy(false) }
  }

  return <section className="admin-section" aria-labelledby="privacy-requests-title">
    <h2 id="privacy-requests-title">Yêu cầu xử lý dữ liệu cá nhân</h2>
    <p>Sau khi duyệt, hệ thống xếp hàng thực thi. Job sẽ thu hồi đăng nhập/thẻ, tách định danh; chứng từ giữ tối thiểu 10 năm trong phạm vi hạn chế.</p>
    <button type="button" className="admin-button secondary" disabled={loading || busy} onClick={() => void refresh()}>Làm mới yêu cầu</button>
    <ErrorNotice error={error} onRetry={() => void refresh()} />
    {loading && <p role="status">Đang tải yêu cầu…</p>}
    {!loading && !requests.length && <p>Chưa có yêu cầu.</p>}
    <label>Lý do quyết định <input value={reason} maxLength={500} onChange={e => setReason(e.target.value)} /></label>
    <label>Phiên bản policy đã phê duyệt <input value={policy} maxLength={100} onChange={e => setPolicy(e.target.value)} /></label>
    {requests.map(row => <article className="admin-card" key={row.id}>
      <h3>Yêu cầu {row.id}</h3>
      <p>Tài khoản: {row.user_id}</p>
      <p>{row.reason}</p>
      <p>Trạng thái: {{ pending: 'Chờ duyệt', approved: 'Đã duyệt', rejected: 'Đã từ chối' }[row.status]} · Thực thi: {{ blocked: 'bị chặn', queued: 'đã xếp hàng', processing: 'đang xử lý', needs_review: 'cần xem xét', completed: 'hoàn tất xử lý' }[row.execution_status]}</p>
      {row.decision_reason && <p>Lý do quyết định: {row.decision_reason} · Policy: {row.policy_version}</p>}
      {row.execution_status === 'completed' && <p>Đã xử lý định danh theo policy. Chứng từ tài chính và số đo được giữ lại; liên kết với tài khoản gốc đã được gỡ, không xóa số liệu tài chính.</p>}
      {row.last_error && <p role="status">{blockers[row.last_error] ?? row.last_error}</p>}
      <ul>{row.blockers.map(code => <li key={code}>{blockers[code] ?? code}</li>)}</ul>
      {row.status === 'pending' && <div className="admin-actions">
        <button type="button" className="admin-button primary" disabled={busy || reason.trim().length < 3 || !policy.trim()} onClick={() => void decide(row.id, 'approved')}>Duyệt yêu cầu</button>
        <button type="button" className="admin-button danger" disabled={busy || reason.trim().length < 3 || !policy.trim()} onClick={() => void decide(row.id, 'rejected')}>Từ chối yêu cầu</button>
      </div>}
      {row.status === 'approved' && row.execution_status !== 'completed' && <div>
        <label>Xác nhận thực thi <input value={confirm} placeholder="EXECUTE_PRIVACY_REQUEST" onChange={e => setConfirm(e.target.value)} /></label>
        <button type="button" className="admin-button danger" disabled={busy || row.blockers.length > 0 || reason.trim().length < 3 || confirm !== 'EXECUTE_PRIVACY_REQUEST'} onClick={() => void process(row.id)}>Xếp hàng thực thi / thử lại</button>
      </div>}
    </article>)}
  </section>
}
