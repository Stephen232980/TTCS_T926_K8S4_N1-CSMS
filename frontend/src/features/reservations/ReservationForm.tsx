import { useEffect, useRef, useState } from 'react'
import { changed, dateLabel, definitiveRejection, json, reservationRequest, type BookingBody, type Reservation } from './api'
import './reservations.css'

function localTime(offsetMinutes: number) {
  const date = new Date(Date.now() + offsetMinutes * 60000)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
function stored(key: string, connectorId: string): BookingBody | null {
  try {
    const data = JSON.parse(sessionStorage.getItem(key) ?? 'null') as BookingBody | null
    return data?.connector_id === connectorId && typeof data.request_id === 'string' && (data.arrival_at === null || (typeof data.arrival_at === 'string' && !Number.isNaN(Date.parse(data.arrival_at)))) ? data : null
  } catch { return null }
}
export function ReservationForm({ connectorId, capability, available, ownReservation = false, ownerId, onChanged }: {
  connectorId: string; capability: string; available: boolean; ownReservation?: boolean; ownerId: string; onChanged: () => void
}) {
  const storageKey = `csms:reservation:${ownerId}:${connectorId}`
  const [attempt, setAttempt] = useState<BookingBody | null>(() => stored(storageKey, connectorId))
  const [expanded, setExpanded] = useState(false)
  const [when, setWhen] = useState(() => attempt?.arrival_at ? 'later' : 'now')
  const [arrival, setArrival] = useState(() => {
    if (!attempt?.arrival_at) return localTime(15)
    const date = new Date(attempt.arrival_at)
    return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0, 16)
  })
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const inFlight = useRef(false), mounted = useRef(true), arrivalInput = useRef<HTMLInputElement>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { if (when === 'later') arrivalInput.current?.focus() }, [when])
  async function probe() {
    if (inFlight.current) return
    inFlight.current = true; setBusy(true); setError('')
    try {
      const result = await reservationRequest<{ status: string }>('/capabilities', json({ connector_id: connectorId }))
      if (!mounted.current) return
      setNotice(result.status === 'supported' ? 'Trụ đã xác minh hỗ trợ đặt chỗ.' : result.status === 'unsupported' ? 'Trụ không hỗ trợ đặt chỗ.' : 'Đang kiểm tra hỗ trợ đặt chỗ. Trạng thái sẽ tự cập nhật.')
      onChanged()
    } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : 'Không kiểm tra được trụ.') }
    finally { inFlight.current = false; if (mounted.current) setBusy(false) }
  }
  async function book() {
    if (inFlight.current || (!available && !attempt)) return
    if (!attempt && when === 'later' && Number.isNaN(new Date(arrival).getTime())) { setError('Chọn thời gian đến hợp lệ trong hai giờ tới.'); return }
    const next = attempt ?? { request_id: crypto.randomUUID(), connector_id: connectorId, arrival_at: when === 'now' ? null : new Date(arrival).toISOString() }
    setAttempt(next); sessionStorage.setItem(storageKey, JSON.stringify(next))
    inFlight.current = true; setBusy(true); setError(''); setNotice('')
    try {
      const result = await reservationRequest<Reservation>('', json(next))
      sessionStorage.removeItem(storageKey)
      if (!mounted.current) return
      setAttempt(null); setExpanded(false); setNotice(`Đã ghi nhận yêu cầu. Hạn giữ đến ${dateLabel(result.expires_at)}. Theo dõi xác nhận tại Đặt chỗ của bạn.`)
      changed(); onChanged()
    } catch (cause) {
      if (definitiveRejection(cause)) { sessionStorage.removeItem(storageKey); if (mounted.current) setAttempt(null) }
      if (mounted.current) setError(definitiveRejection(cause) ? cause.message : 'Kết quả gửi chưa rõ. Thử lại cùng yêu cầu; không đổi đầu nối hoặc giờ đến.')
    } finally { inFlight.current = false; if (mounted.current) setBusy(false) }
  }
  const future = new Date(arrival)
  return <section className="driver-reservation-form" aria-label="Đặt trước đầu nối" aria-busy={busy}>
    <h3>Đặt trước đầu nối</h3>
    <p>Yêu cầu giữ ngay từ bây giờ; chỉ xác nhận thành công khi trụ chấp nhận. Không thu phí đặt trước. Phí không đến chưa áp dụng.</p>
    {capability !== 'supported' && !attempt ? <>
      <p>{capability === 'unsupported' ? 'Trụ chưa hỗ trợ đặt chỗ.' : 'Cần kiểm tra trụ hỗ trợ đặt chỗ trước khi gửi yêu cầu.'}</p>
      <button className="secondary-button" disabled={busy || !available} onClick={() => void probe()}>Kiểm tra hỗ trợ đặt chỗ</button>
    </> : available || attempt ? <>
      {!expanded && !attempt && <button className="secondary-button" onClick={() => setExpanded(true)}>Chọn giờ đến và đặt chỗ</button>}
      {(expanded || attempt) && <form onSubmit={event => { event.preventDefault(); void book() }}>
        <label>Giờ đến<select value={when} disabled={busy || !!attempt} onChange={event => setWhen(event.target.value)}><option value="now">Ngay bây giờ</option><option value="later">Trong hai giờ tới</option></select></label>
        {when === 'later' && <label>Thời gian đến<input ref={arrivalInput} type="datetime-local" required value={arrival} min={localTime(0)} max={localTime(120)} disabled={busy || !!attempt} onChange={event => setArrival(event.target.value)} /></label>}
        <p>Giữ đến {when === 'later' && !Number.isNaN(future.getTime()) ? dateLabel(new Date(future.getTime() + 15 * 60000).toISOString()) : '15 phút sau khi yêu cầu được ghi nhận'}.</p>
        <button className="primary-button" disabled={busy}>{busy ? 'Đang gửi…' : attempt ? 'Thử lại cùng yêu cầu đặt chỗ' : 'Gửi yêu cầu đặt chỗ'}</button>
        {!attempt && <button type="button" className="secondary-button" disabled={busy} onClick={() => setExpanded(false)}>Hủy thao tác</button>}
      </form>}
    </> : <p>{ownReservation ? 'Đầu nối đang được giữ cho bạn. Xem trạng thái tại Đặt chỗ của bạn; khi đã xác nhận, cắm súng rồi bắt đầu sạc.' : 'Đầu nối không còn rảnh. Xem Đặt chỗ của bạn hoặc tải lại trạng thái.'}</p>}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
  </section>
}
