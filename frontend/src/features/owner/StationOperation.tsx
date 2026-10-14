import { useEffect, useRef, useState } from 'react'
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
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    if (confirming) { input.current?.focus(); input.current?.scrollIntoView?.({ block: 'nearest' }) }
  }, [confirming])
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
      <p>{station.status === 'active' ? 'Tạm ngừng để bảo trì sẽ ẩn trạm khỏi tìm kiếm và chặn phiên mới. Phiên đang chạy tiếp tục bình thường.' : 'Bật trạm sau khi đã khai báo đầu nối và thiết lập biểu giá có hiệu lực.'}</p>
      {!confirming && <button type="button" className="secondary-button" disabled={busy} onClick={() => station.status === 'active' ? setConfirming(true) : void change('active')}>{busy ? 'Đang lưu…' : station.status === 'active' ? 'Tạm ngừng trạm' : 'Bật trạm'}</button>}
      {confirming && <form onSubmit={event => { event.preventDefault(); void change('suspended') }}>
        <label>Lý do tạm ngừng<input ref={input} required maxLength={500} value={reason} disabled={busy} onChange={event => setReason(event.target.value)} /></label>
        <button className="primary-button" disabled={busy || !reason.trim()}>{busy ? 'Đang lưu…' : 'Xác nhận tạm ngừng'}</button>
        <button type="button" className="secondary-button" disabled={busy} onClick={() => { setConfirming(false); setReason(''); setError('') }}>Hủy</button>
      </form>}
    </>}
    {notice && <p role="status">{notice}</p>}
    {error && <div role="alert"><p>{error}</p><button type="button" className="secondary-button" disabled={busy} onClick={() => { onReload(); setError(''); setConfirming(false); setReason('') }}>Tải lại trạm</button></div>}
  </section>
}
