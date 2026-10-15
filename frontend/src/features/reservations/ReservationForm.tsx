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
  const [expanded, setExpanded] = useState(!!attempt)
  const [when, setWhen] = useState(() => attempt?.arrival_at ? 'later' : 'now')
  const [arrival, setArrival] = useState(() => {
    if (!attempt?.arrival_at) return localTime(15)
    const date = new Date(attempt.arrival_at)
    return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0, 16)
  })
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [policy, setPolicy] = useState<{fee_vnd:number; version:number} | null>(null)
  const [acceptedFee, setAcceptedFee] = useState(false)
  const [policyRevision, setPolicyRevision] = useState(0)
  const inFlight = useRef(false), mounted = useRef(true), arrivalInput = useRef<HTMLInputElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const probeController = useRef<AbortController | null>(null)
  const probeSawPending = useRef(false)
  useEffect(() => {
    const element = dialog.current
    if (expanded && element && !element.open) element.showModal()
    if (!expanded && element?.open) {element.close(); trigger.current?.focus()}
  }, [expanded])
  function closePopup() {
    if (busy && attempt) return
    probeController.current?.abort()
    setExpanded(false)
    setChecking(false)
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { if (when === 'later') arrivalInput.current?.focus() }, [when])
  useEffect(() => {
    if (!checking) return
    if (capability === 'unverified') probeSawPending.current = true
    if (capability === 'supported' || (capability === 'unsupported' && probeSawPending.current)) {
      const timer = window.setTimeout(() => {
        setChecking(false)
        setNotice(capability === 'supported' ? '' : 'Trụ không hỗ trợ đặt chỗ. Chọn đầu nối khác.')
      }, 0)
      return () => window.clearTimeout(timer)
    }
    const timer = window.setTimeout(() => {
      setChecking(false)
      setError('Chưa nhận được kết quả từ trụ. Thử lại đặt chỗ hoặc chọn đầu nối khác.')
    }, 20000)
    return () => window.clearTimeout(timer)
  }, [checking, capability])
  useEffect(() => {
    if (!expanded || !available || capability !== 'supported' || attempt) return
    const controller = new AbortController()
    reservationRequest<{fee_vnd:number; version:number}>(`/policy?connector_id=${encodeURIComponent(connectorId)}`, {signal:controller.signal}).then(next => {
      if (!Number.isInteger(next.fee_vnd) || next.fee_vnd < 0 || !Number.isInteger(next.version)) throw new Error('Invalid policy')
      if (!controller.signal.aborted) {
        setPolicy(next); setAcceptedFee(false)
        setError(value => /^(Chưa nhận được|Máy chủ chưa phản hồi|Không kiểm tra được)/.test(value) ? '' : value)
        setNotice(value => value.includes('hỗ trợ đặt chỗ') ? '' : value)
      }
    }).catch(() => {if (!controller.signal.aborted) setError('Không tải được phí không đến. Tải lại trạng thái trước khi đặt.')})
    return () => controller.abort()
  }, [expanded, available, capability, connectorId, policyRevision, attempt])
  async function probe() {
    if (inFlight.current) return
    const controller = new AbortController()
    probeSawPending.current = capability === 'unverified'
    probeController.current = controller
    const timeout = window.setTimeout(() => controller.abort(), 10000)
    inFlight.current = true; setBusy(true); setChecking(true); setError('')
    try {
      const result = await reservationRequest<{ status: string }>('/capabilities', {...json({ connector_id: connectorId }), signal:controller.signal})
      if (!mounted.current) return
      if (result.status !== 'unverified') setChecking(false)
      setNotice(result.status === 'supported' ? 'Trụ đã xác minh hỗ trợ đặt chỗ.' : result.status === 'unsupported' ? 'Trụ không hỗ trợ đặt chỗ. Chọn đầu nối khác.' : 'Đang kiểm tra hỗ trợ đặt chỗ…')
      onChanged()
    } catch (cause) { if (mounted.current) {setChecking(false); setError(controller.signal.aborted ? 'Máy chủ chưa phản hồi. Thử lại đặt chỗ.' : cause instanceof Error ? cause.message : 'Không kiểm tra được trụ.')} }
    finally { window.clearTimeout(timeout); probeController.current = null; inFlight.current = false; if (mounted.current) setBusy(false) }
  }
  async function book() {
    if (inFlight.current || (!available && !attempt)) return
    if (!attempt && (!policy || policy.fee_vnd > 0 && !acceptedFee)) return
    if (!attempt && when === 'later' && Number.isNaN(new Date(arrival).getTime())) { setError('Chọn thời gian đến hợp lệ trong hai giờ tới.'); return }
    const next = attempt ?? { request_id: crypto.randomUUID(), connector_id: connectorId, arrival_at: when === 'now' ? null : new Date(arrival).toISOString(), accepted_fee_vnd: policy!.fee_vnd, accepted_policy_version: policy!.version }
    setAttempt(next); sessionStorage.setItem(storageKey, JSON.stringify(next))
    inFlight.current = true; setBusy(true); setError(''); setNotice('')
    try {
      const result = await reservationRequest<Reservation>('', json(next))
      sessionStorage.removeItem(storageKey)
      if (!mounted.current) return
      setAttempt(null); setExpanded(false); setNotice(`Đã ghi nhận yêu cầu. Hạn giữ đến ${dateLabel(result.expires_at)}. Theo dõi xác nhận tại Đặt chỗ của bạn.`)
      changed(); onChanged()
    } catch (cause) {
      if (definitiveRejection(cause)) { sessionStorage.removeItem(storageKey); if (mounted.current) {setAttempt(null); setPolicy(null); setPolicyRevision(value => value + 1)} }
      if (mounted.current) setError(definitiveRejection(cause) ? cause.message : 'Kết quả gửi chưa rõ. Thử lại cùng yêu cầu; không đổi đầu nối hoặc giờ đến.')
    } finally { inFlight.current = false; if (mounted.current) setBusy(false) }
  }
  return <section className="driver-reservation-form" aria-label="Đặt trước đầu nối" aria-busy={busy}>
    <button ref={trigger} type="button" className="secondary-button driver-reservation-trigger" aria-haspopup="dialog" aria-expanded={expanded} disabled={busy || checking || (!available && !attempt)} onClick={() => {
      setExpanded(true)
      if (capability !== 'supported' && !attempt) void probe()
    }}>{checking ? 'Đang kiểm tra hỗ trợ đặt chỗ…' : 'Đặt trước đầu nối'}</button>
    <dialog ref={dialog} className="driver-reservation-dialog" aria-labelledby={`reservation-title-${connectorId}`} onCancel={event => {event.preventDefault(); closePopup()}}>
    <h2 id={`reservation-title-${connectorId}`}>Đặt trước đầu nối</h2>
    {expanded && <div className="driver-reservation-fields">
    <ul className="driver-reservation-summary">
      <li>{attempt ? `Phí không đến: ${attempt.accepted_fee_vnd ?? 0}đ.` : policy ? `Phí không đến: ${policy.fee_vnd}đ.` : 'Đang tải phí không đến…'}</li>
      <li>Không thu phí đặt trước.</li>
      <li>Có hiệu lực trong 15 phút.</li>
    </ul>
    {capability !== 'supported' && !attempt ? <>
      <p>{capability === 'unsupported' ? 'Trụ chưa hỗ trợ đặt chỗ.' : 'Cần kiểm tra trụ hỗ trợ đặt chỗ trước khi gửi yêu cầu.'}</p>
    </> : available || attempt ? <>
      {(expanded || attempt) && <form onSubmit={event => { event.preventDefault(); void book() }}>
        <label>Giờ đến<select value={when} disabled={busy || !!attempt} onChange={event => setWhen(event.target.value)}><option value="now">Ngay bây giờ</option><option value="later">Trong hai giờ tới</option></select></label>
        {when === 'later' && <label>Thời gian đến<input ref={arrivalInput} type="datetime-local" required value={arrival} min={localTime(0)} max={localTime(120)} disabled={busy || !!attempt} onChange={event => setArrival(event.target.value)} /></label>}
        {!attempt && policy && policy.fee_vnd > 0 && <label className="reservation-fee-consent"><input type="checkbox" checked={acceptedFee} onChange={event => setAcceptedFee(event.target.checked)} disabled={busy} />Tôi đồng ý.</label>}
        <button className="primary-button" disabled={busy || (!attempt && (!policy || policy.fee_vnd > 0 && !acceptedFee))}>{busy ? 'Đang gửi…' : attempt ? 'Thử lại cùng yêu cầu đặt chỗ' : 'Xác nhận đặt chỗ'}</button>
      </form>}
    </> : <p>{ownReservation ? 'Đầu nối đang được giữ cho bạn. Xem trạng thái tại Đặt chỗ của bạn; khi đã xác nhận, cắm súng rồi bắt đầu sạc.' : 'Đầu nối không còn rảnh. Xem Đặt chỗ của bạn hoặc tải lại trạng thái.'}</p>}
    {error && <p role="alert">{error}</p>}
    {!checking && !busy && capability !== 'supported' && <button type="button" className="secondary-button" onClick={() => void probe()}>Thử lại kiểm tra hỗ trợ</button>}
    {error && available && capability === 'supported' && !attempt && <button type="button" className="secondary-button" onClick={() => {setError(''); setPolicy(null); setPolicyRevision(value => value + 1)}}>Tải lại mức phí</button>}
    {notice && <p role="status">{notice}</p>}
    </div>}
    <button type="button" className="secondary-button driver-reservation-cancel" disabled={busy && !!attempt} onClick={closePopup}>Hủy</button>
    </dialog>
    {!expanded && attempt && <p>Yêu cầu trước chưa rõ kết quả. Mở lại để thử lại cùng yêu cầu.</p>}
    {!expanded && ownReservation && <p>Đầu nối đang được giữ cho bạn. Xem trạng thái tại Đặt chỗ của bạn.</p>}
    {!expanded && notice && <p role="status">{notice}</p>}
  </section>
}
