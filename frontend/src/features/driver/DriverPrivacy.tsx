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
  return <section className="driver-wallet-stack">
    <p>Gửi yêu cầu xử lý dữ liệu cá nhân. Tài khoản vẫn hoạt động trong thời gian xem xét; gửi hoặc duyệt yêu cầu chưa thực thi xóa.</p>
    <ErrorNotice error={error} onRetry={() => void refresh()} />
    <button className="secondary-button" type="button" disabled={loading || busy} onClick={() => void refresh()}>Cập nhật trạng thái</button>
    {loading && <p role="status">Đang tải yêu cầu…</p>}
    {!loading && !active && <form onSubmit={event => void submit(event)}>
      <label>Mật khẩu hiện tại <input type="password" autoComplete="current-password" value={password} maxLength={1024} onChange={e => setPassword(e.target.value)} required /></label>
      <label>Lý do yêu cầu <textarea value={reason} maxLength={500} onChange={e => setReason(e.target.value)} /></label>
      <button className="primary-button" disabled={busy || !password} type="submit">{busy ? 'Đang gửi…' : 'Gửi yêu cầu'}</button>
    </form>}
    {requests.map(row => <article key={row.id}>
      <h2>Yêu cầu {row.id}</h2>
      <p>{{ pending: 'Chờ duyệt', approved: 'Đã duyệt, chưa thực thi', rejected: 'Đã từ chối' }[row.status]}</p>
      {row.decision_reason && <p>Lý do quyết định: {row.decision_reason}</p>}
      {row.policy_version && <p>Phiên bản policy: {row.policy_version}</p>}
      <p>Yêu cầu được xử lý theo CSMS-PRIVACY-2026-01. Khi bắt đầu thực thi, đăng nhập và thẻ sẽ bị thu hồi. Chứng từ tài chính giữ tối thiểu 10 năm trong phạm vi hạn chế; không xóa toàn bộ lịch sử.</p>
      {row.blockers.includes('refund_required') && <p>Cần xử lý hoàn tiền và đối chiếu chứng từ.</p>}
      {row.blockers.includes('debt_resolution_required') && <p>Cần xử lý khoản nợ trước khi tiếp tục.</p>}
      {row.blockers.includes('legal_hold_or_unsettled_charging') && <p>Có tạm giữ hoặc phiên sạc chưa quyết toán.</p>}
      {row.blockers.includes('connector_release_required') && <p>Cần xác nhận đã rút cáp.</p>}
      {row.blockers.includes('reservation_or_fee_pending') && <p>Cần hoàn tất xử lý đặt chỗ hoặc phí đặt chỗ.</p>}
    </article>)}
  </section>
}
