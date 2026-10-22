import { useEffect, useState, type FormEvent } from 'react'
import { adminRequest, writeJson } from '../admin/adminApi'
import { ErrorNotice } from '../admin/AdminShared'
import type { PrivacyReceipt } from '../admin/privacyApi'

export function DriverPrivacy() {
  const [requests, setRequests] = useState<PrivacyReceipt[]>([])
  const [password, setPassword] = useState('')
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    const controller = new AbortController()
    void adminRequest<PrivacyReceipt[]>('/driver/privacy/requests', { signal: controller.signal }).then(data => {
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
    try { setRequests(await adminRequest<PrivacyReceipt[]>('/driver/privacy/requests')) }
    catch (err) { setError(err) }
    finally { setLoading(false) }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const receipt = await adminRequest<PrivacyReceipt>('/driver/privacy/anonymize-request', writeJson('POST', {
        current_password: password, reason: reason.trim() || null,
      }))
      setRequests(rows => [receipt, ...rows.filter(row => row.id !== receipt.id)])
      setReason('')
    } catch (err) { setError(err) }
    finally { setPassword(''); setBusy(false) }
  }

  const active = requests.some(row => row.status !== 'rejected')
  const statusText = (row: PrivacyReceipt) => row.execution_status === 'completed' ? 'Đã hoàn tất ẩn danh' : row.status === 'rejected' ? 'Đã từ chối' : row.status === 'pending' ? 'Chờ duyệt' : row.execution_status === 'processing' ? 'Đang xử lý' : row.execution_status === 'needs_review' || row.execution_status === 'blocked' ? 'Cần kiểm tra trước khi xử lý' : 'Đã duyệt · Chờ xử lý'
  return <section className="driver-privacy" aria-label="Yêu cầu ẩn danh tài khoản">
    <div className="driver-privacy-intro">
      <h2>Ẩn danh tài khoản</h2>
      <p>Sau khi yêu cầu được duyệt và xử lý, thông tin định danh được gỡ khỏi tài khoản và lịch sử sạc. Hóa đơn, sổ cái và số liệu doanh thu vẫn được giữ lại.</p>
      <p>Việc gửi yêu cầu chưa làm thay đổi tài khoản. Khi bắt đầu xử lý, hệ thống sẽ thu hồi đăng nhập và thẻ sạc của bạn.</p>
    </div>
    <ErrorNotice error={error} onRetry={() => void refresh()} />
    {loading && <p role="status">Đang tải yêu cầu…</p>}
    {!loading && !error && !active && <form className="driver-privacy-form" onSubmit={event => void submit(event)}>
      <h2>Gửi yêu cầu ẩn danh</h2>
      <label>Mật khẩu hiện tại<input type="password" autoComplete="current-password" value={password} maxLength={1024} disabled={busy} onChange={e => setPassword(e.target.value)} required /></label>
      <label>Lý do yêu cầu <span className="driver-subtle">Không bắt buộc</span><textarea rows={3} value={reason} maxLength={500} disabled={busy} onChange={e => setReason(e.target.value)} /></label>
      <p>Bạn cần hoàn tất phiên sạc, đặt chỗ và xử lý số dư hoặc khoản nợ trước khi hệ thống có thể thực hiện ẩn danh.</p>
      <button className="primary-button" disabled={busy || !password} type="submit">{busy ? 'Đang gửi…' : 'Gửi yêu cầu'}</button>
    </form>}
    <section className="driver-privacy-history" aria-label="Trạng thái yêu cầu ẩn danh">
      <div className="driver-privacy-history-heading"><h2>Yêu cầu của bạn</h2><button className="secondary-button" type="button" disabled={loading || busy} onClick={() => void refresh()}>Cập nhật trạng thái</button></div>
      {!loading && !error && !requests.length && <p>Bạn chưa gửi yêu cầu ẩn danh.</p>}
      {requests.map(row => <article key={row.id}>
        <strong className="driver-privacy-status">{statusText(row)}</strong>
        {row.created_at && <p>Gửi lúc {new Date(row.created_at).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' })}</p>}
        {row.reason && <p>Lý do yêu cầu: {row.reason}</p>}
        {row.decision_reason && <p>Phản hồi: {row.decision_reason}</p>}
        {row.execution_status === 'completed' && <p>Liên kết với tài khoản gốc đã được gỡ; chứng từ tài chính và số liệu sạc được giữ lại.</p>}
        {row.blockers.includes('refund_required') && <p>Cần xử lý hoàn tiền và đối chiếu chứng từ.</p>}
        {row.blockers.includes('debt_resolution_required') && <p>Cần xử lý khoản nợ trước khi tiếp tục.</p>}
        {row.blockers.includes('legal_hold_or_unsettled_charging') && <p>Có nghĩa vụ đang chờ xử lý hoặc phiên sạc chưa quyết toán.</p>}
        {row.blockers.includes('connector_release_required') && <p>Cần xác nhận đã rút cáp.</p>}
        {row.blockers.includes('reservation_or_fee_pending') && <p>Cần hoàn tất xử lý đặt chỗ hoặc phí đặt chỗ.</p>}
        <details><summary>Thông tin yêu cầu</summary><p>Yêu cầu {row.id}</p>{row.policy_version && <p>Chính sách áp dụng: {row.policy_version}</p>}</details>
      </article>)}
    </section>
  </section>
}
