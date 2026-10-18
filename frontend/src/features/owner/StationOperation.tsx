import { useEffect, useId, useRef, useState } from 'react'
import type { Station, StationStatus } from '../stations/model/station'
import { OwnerApiError, ownerRequest } from './ownerApi'
import './stationOperation.css'

const messages: Record<string, string> = {
  station_admin_blocked: 'Trạm bị quản trị viên khóa. Bạn không thể tự mở lại.',
  station_version_conflict: 'Thông tin trạm đã thay đổi. Tải lại trạm trước khi tiếp tục.',
  station_connector_required: 'Khai báo ít nhất một đầu nối trước khi bật trạm.',
  station_tariff_required: 'Thiết lập biểu giá có hiệu lực và đủ các khung giờ trước khi bật trạm.',
  station_configuration_incomplete: 'Kiểm tra tên, địa chỉ và tọa độ trước khi bật trạm.',
  power_unavailable: 'Chia tải chưa sẵn sàng. Kiểm tra cấu hình công suất trước khi bật trạm.',
  station_transition_invalid: 'Trạm đã đổi trạng thái. Tải lại trạm để kiểm tra.',
}

export function StationOperation({ station, onChanged, onReload }: {
  station: Station
  onChanged: (status: StationStatus, version: number) => void
  onReload: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    const modal = dialog.current
    if (!modal) return
    if (confirming) {
      if (!modal.open) {
        if (modal.showModal) modal.showModal()
        else modal.setAttribute('open', '')
      }
      input.current?.focus({ preventScroll: true })
    } else if (modal.open) {
      if (modal.close) modal.close()
      else modal.removeAttribute('open')
      trigger.current?.focus({ preventScroll: true })
    }
  }, [confirming])
  function dismiss() { if (!busy) { setConfirming(false); setReason(''); setError('') } }
  async function change(status: 'active' | 'suspended') {
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await ownerRequest<{ status: StationStatus; status_version: number }>(`/owner/stations/${encodeURIComponent(station.id)}/operation`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, expected_version: station.statusVersion ?? 1, reason: status === 'suspended' ? reason.trim() : '' }),
      })
      if (!mounted.current) return
      onChanged(result.status, result.status_version)
      setConfirming(false); setReason('')
      setNotice(status === 'active' ? 'Đã bật trạm. Tài xế có thể tìm thấy trạm sau khi làm mới.' : 'Đã tạm ngừng trạm. Phiên đang chạy vẫn được kết thúc bình thường.')
    } catch (cause) {
      if (mounted.current) setError(cause instanceof OwnerApiError && typeof cause.detail === 'string' ? messages[cause.detail] ?? cause.message : 'Không lưu được trạng thái trạm. Hãy thử lại với thao tác hiện tại.')
    } finally { if (mounted.current) setBusy(false) }
  }
  return <section className="owner-operation" aria-label="Hoạt động của trạm" aria-busy={busy}>
    {station.status === 'blocked' ? <p>Trạm bị quản trị viên khóa. Liên hệ quản trị viên để mở lại.</p> : <>
      <button ref={trigger} type="button" className={`secondary-button ${station.status === 'active' ? 'operation-suspend' : 'operation-enable'}`} disabled={busy} onClick={() => { setError(''); if (station.status === 'active') setConfirming(true); else void change('active') }}>{busy ? 'Đang lưu…' : station.status === 'active' ? 'Tạm ngừng trạm' : 'Bật trạm'}</button>
      <dialog ref={dialog} className="owner-operation-dialog" aria-labelledby={titleId} onCancel={event => { event.preventDefault(); dismiss() }}>
        <form onSubmit={event => { event.preventDefault(); void change('suspended') }}>
          <div className="owner-operation-dialog-heading"><h2 id={titleId}>Tạm ngừng {station.name}</h2><button type="button" className="secondary-button" aria-label="Đóng xác nhận tạm ngừng" disabled={busy} onClick={dismiss}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg></button></div>
          <p>Ẩn trạm và chặn phiên mới. Phiên đang chạy tiếp tục bình thường.</p>
          <label>Lý do tạm ngừng<input ref={input} required maxLength={500} value={reason} disabled={busy} onChange={event => setReason(event.target.value)} /></label>
          {error && <div role="alert"><p>{error}</p><button type="button" className="secondary-button" disabled={busy} onClick={() => { onReload(); dismiss() }}>Tải lại trạm</button></div>}
          <div className="owner-operation-dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={dismiss}>Hủy</button><button className="primary-button operation-suspend" disabled={busy || !reason.trim()}>{busy ? 'Đang lưu…' : 'Xác nhận tạm ngừng'}</button></div>
        </form>
      </dialog>
    </>}
    {notice && <p role="status">{notice}</p>}
    {error && !confirming && <div role="alert"><p>{error}</p><button type="button" className="secondary-button" disabled={busy} onClick={() => { onReload(); setError(''); setConfirming(false); setReason('') }}>Tải lại trạm</button></div>}
  </section>
}
