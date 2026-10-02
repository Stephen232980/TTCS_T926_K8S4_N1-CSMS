import { useState } from 'react'
import type { FormEvent } from 'react'

interface Props {
  sessionId: number
  latestMeter: string | null
  startMeter: string
  meterAt: string | null
  onSubmit: (reason: string) => Promise<void>
  onCancel: () => void
}

export function ManualCloseForm({ sessionId, latestMeter, startMeter, meterAt, onSubmit, onCancel }: Props) {
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const validMeter = latestMeter !== null && Number(latestMeter) >= Number(startMeter) && Number(startMeter) >= 0
  const energy = validMeter ? ((Number(latestMeter) - Number(startMeter)) / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 6 }) : null

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!reason.trim() || !confirmed || !validMeter || saving) return
    setSaving(true); setError('')
    try { await onSubmit(reason.trim()) }
    catch (err) { setError(err instanceof Error ? err.message : 'Không đóng được phiên. Hãy thử lại.') }
    finally { setSaving(false) }
  }

  return <form className="charging-close-form" aria-label={`Đóng tay phiên ${sessionId}`} onSubmit={event => void submit(event)}>
    <h3>Đóng tay phiên #{sessionId}</h3>
    <p>Thao tác này chỉ đóng hồ sơ phiên trong CSMS. Trụ sẽ không nhận lệnh dừng sạc.</p>
    <dl className="ocpp-facts"><div><dt>Điện năng dự kiến chốt</dt><dd>{energy === null ? 'Chưa có số đo hợp lệ' : `${energy} kWh`}</dd></div><div><dt>Số đo cuối nhận từ trụ</dt><dd>{meterAt ? new Date(meterAt).toLocaleString('vi-VN') : 'Chưa có'}</dd></div></dl>
    <p className="ocpp-refresh-note">Hệ thống tính lại bằng số đo cuối tại thời điểm lưu; số đo này có thể chưa bao gồm điện năng khi trụ mất mạng.</p>
    {!validMeter && <p role="alert">Hãy kiểm tra số đo hoặc chờ trụ gửi dữ liệu trước khi đóng tay.</p>}
    <div className="form-field"><label htmlFor={`close-reason-${sessionId}`}>Lý do đóng tay</label><textarea id={`close-reason-${sessionId}`} required maxLength={500} rows={3} value={reason} onChange={e => setReason(e.target.value)} disabled={saving} /></div>
    <label className="charging-close-confirm"><input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)} disabled={saving} />Tôi đã kiểm tra trụ và xác nhận đóng hồ sơ phiên này.</label>
    {error && <p className="form-submit-error" role="alert">{error}</p>}
    <div className="charging-session-actions"><button className="secondary-button" type="button" onClick={onCancel} disabled={saving}>Hủy</button><button className="primary-button" type="submit" disabled={saving || !validMeter || !reason.trim() || !confirmed}>{saving ? 'Đang đóng…' : 'Xác nhận đóng phiên'}</button></div>
  </form>
}
