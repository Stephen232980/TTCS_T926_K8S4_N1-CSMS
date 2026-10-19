import { useEffect, useState } from 'react'
import { dateTime } from './adminApi'
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
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    void fetchPrivacyRequests(controller.signal).then(data => {
      if (!controller.signal.aborted) setRequests(data)
    }).catch(err => {
      if (!controller.signal.aborted) setError(err)
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [revision])
  function refresh() { setLoading(true); setError(null); setRevision(v => v + 1) }
  return <section className="admin-privacy-requests" aria-labelledby="privacy-requests-title" aria-busy={loading}>
    <div className="admin-privacy-toolbar"><h2 id="privacy-requests-title">Yêu cầu xử lý dữ liệu cá nhân</h2>
      <button type="button" disabled={loading} onClick={refresh}>Làm mới yêu cầu</button>
    </div>
    <p className="admin-privacy-policy">Sau khi duyệt, hệ thống ẩn danh tài khoản và gỡ liên kết định danh với lịch sử sạc. Hóa đơn, sổ cái và số liệu doanh thu được giữ lại.</p>
    <ErrorNotice error={error} onRetry={refresh} />
    {loading && <p role="status">Đang tải yêu cầu…</p>}
    {!loading && !error && !requests.length && <p>Chưa có yêu cầu.</p>}
    {requests.map(row => <RequestReview key={row.id} row={row} onUpdate={receipt => setRequests(rows => rows.map(item => item.id === receipt.id ? receipt : item))} />)}
  </section>
}
const statusLabels = { pending: 'Chờ duyệt', approved: 'Đã duyệt', rejected: 'Đã từ chối' }
const executionLabels = { blocked: 'bị chặn', queued: 'đã xếp hàng', processing: 'đang xử lý', needs_review: 'cần xem xét', completed: 'hoàn tất xử lý' }
function RequestReview({ row, onUpdate }: { row: PrivacyReceipt; onUpdate: (row: PrivacyReceipt) => void }) {
  const [reason, setReason] = useState('')
  const [policy, setPolicy] = useState(DEFAULT_PRIVACY_POLICY_VERSION)
  const [confirmedBalance, setConfirmedBalance] = useState<number | null | false>(false)
  const confirm = confirmedBalance !== false && confirmedBalance === (row.wallet_balance_vnd ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const retryable = row.status === 'approved' && (row.execution_status === 'needs_review' || row.execution_status === 'blocked')
  async function decide(decision: 'approved' | 'rejected') {
    setBusy(true); setError(null)
    try { onUpdate(await reviewPrivacyRequest(row.id, decision, reason.trim(), policy.trim())); setReason('') }
    catch (err) { setError(err) } finally { setBusy(false) }
  }
  const refundRequired = row.blockers.includes('refund_required') && typeof row.wallet_balance_vnd === 'number' && row.wallet_balance_vnd > 0
  const unresolved = row.blockers.filter(code => code !== 'refund_required' || !refundRequired)
  const refundAmount = new Intl.NumberFormat('vi-VN').format(row.wallet_balance_vnd ?? 0)
  async function retry() {
    setBusy(true); setError(null)
    try { onUpdate(await executePrivacyRequest(row.id, `${refundRequired ? 'Xác nhận đã hoàn tiền bên ngoài và tiếp tục ẩn danh' : 'Xác nhận thử lại xử lý ẩn danh'}${reason.trim() ? `: ${reason.trim()}` : ''}`.slice(0, 500), 'EXECUTE_PRIVACY_REQUEST', refundRequired ? { external_refund_confirmed: true, expected_balance_vnd: row.wallet_balance_vnd! } : undefined)); setConfirmedBalance(false); setReason('') }
    catch (err) { setError(err) } finally { setBusy(false) }
  }
  return <details className="admin-privacy-request" open={row.status === 'pending' ? true : undefined}>
    <summary><strong>{statusLabels[row.status] ?? 'Cần kiểm tra trạng thái'}</strong>Yêu cầu {dateTime(row.created_at)} · {executionLabels[row.execution_status] ?? 'chưa xác định'}</summary>
    <div className="admin-privacy-detail">
      <dl><dt>Mã yêu cầu</dt><dd>{row.id}</dd><dt>Mã tài khoản</dt><dd>{row.user_id}</dd><dt>Lý do yêu cầu</dt><dd>{row.reason}</dd></dl>
      <p>Trạng thái: {statusLabels[row.status]} · Thực thi: {executionLabels[row.execution_status]}</p>
      {row.decision_reason && <p>Lý do quyết định: {row.decision_reason} · Chính sách: {row.policy_version}</p>}
      {row.execution_status === 'completed' && <p>Đã gỡ liên kết với tài khoản gốc; chứng từ tài chính và số đo được giữ lại.</p>}
      {row.last_error && <p role="status">{blockers[row.last_error] ?? 'Xử lý chưa hoàn tất. Hãy kiểm tra hồ sơ trước khi thử lại.'}</p>}
      {row.blockers.length > 0 && <div><strong>Cần giải quyết trước khi xử lý</strong><ul className="admin-privacy-blockers">{row.blockers.map(code => <li key={code}>{blockers[code] ?? 'Có nghĩa vụ chưa hoàn tất; cần kiểm tra hồ sơ.'}</li>)}</ul></div>}
      <ErrorNotice error={error} />
      {(row.status === 'pending' || retryable) && <div className="admin-privacy-form">
        <label>{row.status === 'pending' ? 'Lý do quyết định' : 'Ghi chú xử lý (không bắt buộc)'}<input value={reason} maxLength={500} disabled={busy} onChange={e => setReason(e.target.value)} /></label>
        {row.status === 'pending' && <>
          <label>Chính sách đã phê duyệt<input value={policy} maxLength={100} disabled={busy} onChange={e => setPolicy(e.target.value)} /></label>
          <div className="admin-actions"><button type="button" className="admin-primary" disabled={busy || reason.trim().length < 3 || !policy.trim()} onClick={() => void decide('approved')}>Duyệt yêu cầu</button>
          <button type="button" className="admin-danger" disabled={busy || reason.trim().length < 3 || !policy.trim()} onClick={() => void decide('rejected')}>Từ chối yêu cầu</button></div>
        </>}
        {retryable && <>
          <label className="admin-privacy-confirm"><input type="checkbox" checked={confirm} disabled={busy} onChange={e => setConfirmedBalance(e.target.checked ? (row.wallet_balance_vnd ?? null) : false)} />{refundRequired ? `Tôi xác nhận đã hoàn ${refundAmount}đ bên ngoài. Ghi giảm ví về 0đ và tiếp tục ẩn danh.` : 'Tôi xác nhận thử lại xử lý ẩn danh theo chính sách đã duyệt.'}</label>
          <button type="button" className="admin-danger" disabled={busy || unresolved.length > 0 || !confirm} onClick={() => void retry()}>Thử lại xử lý</button>
        </>}
        {busy && <p role="status">Đang xử lý yêu cầu…</p>}
      </div>}
    </div>
  </details>
}
