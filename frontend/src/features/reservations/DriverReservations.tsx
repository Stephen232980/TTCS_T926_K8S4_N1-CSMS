import { useEffect, useRef, useState } from 'react'
import { changed, dateLabel, definitiveRejection, json, labels, reservationRequest, type Reservation, type ReservationPage } from './api'
import './reservations.css'

export function DriverReservations({ ownerId, focusedId }: { ownerId: string; focusedId?: string }) {
  const [result, setResult] = useState<ReservationPage | null>(null)
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(!!focusedId)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState('')
  const [revision, setRevision] = useState(0)
  const generation = useRef(0), mounted = useRef(true), inFlight = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running || document.hidden) return
      running = true
      const version = generation.current
      try {
        const payload = await reservationRequest<ReservationPage | Reservation>(focusedId ? `/${encodeURIComponent(focusedId)}` : `?page=${page}`, { signal: controller.signal })
        const next = focusedId ? {items:[payload as Reservation],page:1,total_pages:1,total:1,generated_at:(payload as Reservation).updated_at} : payload as ReservationPage
        if (!Array.isArray(next.items) || next.items.some(item => !Object.hasOwn(labels, item.status))) throw new Error('Không đọc được trạng thái đặt chỗ.')
        if (!controller.signal.aborted && version === generation.current) { setResult(next); setPage(next.page); setError('') }
      } catch (cause) { if (!controller.signal.aborted && version === generation.current) setError(cause instanceof Error ? cause.message : 'Không tải được đặt chỗ.') }
      finally { running = false }
    }
    const start = window.setTimeout(() => void load(), 0)
    const timer = window.setInterval(() => void load(), 5000)
    const updated = () => { setExpanded(true); void load() }
    const visible = () => { if (!document.hidden) void load() }
    window.addEventListener('csms:reservation-changed', updated)
    document.addEventListener('visibilitychange', visible)
    return () => { controller.abort(); window.clearTimeout(start); window.clearInterval(timer); window.removeEventListener('csms:reservation-changed', updated); document.removeEventListener('visibilitychange', visible) }
  }, [page, revision, focusedId])
  async function cancel(item: Reservation) {
    if (inFlight.current || !item.can_cancel || error) return
    const key = `csms:reservation-cancel:${ownerId}:${item.id}`
    const requestId = sessionStorage.getItem(key) || crypto.randomUUID()
    sessionStorage.setItem(key, requestId)
    inFlight.current = true; setBusy(item.id); setActionError(''); generation.current++
    try {
      const next = await reservationRequest<Reservation>(`/${encodeURIComponent(item.id)}/cancel`, json({ request_id: requestId }))
      sessionStorage.removeItem(key)
      if (!mounted.current) return
      setResult(previous => previous ? { ...previous, items: previous.items.map(row => row.id === next.id ? next : row) } : previous)
      changed()
    } catch (cause) {
      if (definitiveRejection(cause)) sessionStorage.removeItem(key)
      if (mounted.current) setActionError(definitiveRejection(cause) ? cause.message : 'Kết quả hủy chưa rõ. Thử lại để gửi cùng yêu cầu hủy.')
    } finally { inFlight.current = false; if (mounted.current) setBusy('') }
  }
  const current = result?.items.find(item => ['pending', 'active', 'uncertain', 'cancel_pending', 'expiry_release_pending'].includes(item.status))
  return <details className="driver-reservations" open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}>
    <summary>Đặt chỗ của bạn{current ? ` · ${labels[current.status]}` : result ? ` (${result.total})` : ' · Đang tải'}</summary>
    <div className="driver-reservation-content">
      {error && <p role="alert">{error}{result && ' Dữ liệu đang hiển thị có thể cũ.'}</p>}
      {actionError && <p role="alert">{actionError}</p>}
      <button className="secondary-button" disabled={!!busy} onClick={() => setRevision(value => value + 1)}>Tải lại đặt chỗ</button>
      {!result && !error && <p role="status">Đang tải đặt chỗ…</p>}
      {result?.items.length === 0 && <p>Bạn chưa có đặt chỗ.</p>}
      {result?.items.map(item => <article key={item.id}>
        <h3>{item.station_name}</h3><p>{item.charge_point_code} · Đầu nối {item.connector_number}</p>
        <strong>{labels[item.status]}</strong>
        <p>Giờ đến {dateLabel(item.arrival_at)} · Hạn giữ {dateLabel(item.expires_at)}</p>
        <p>Phí không đến đã chấp nhận: {Number(item.no_show_fee_vnd ?? 0).toLocaleString('vi-VN')}đ · {item.fee_decision === 'charged' ? 'Đã thu phí' : item.fee_decision === 'review' ? 'Cần kiểm tra, không tự thu thêm hoặc hoàn phí' : ['waived','legacy_exempt'].includes(item.fee_decision ?? '') ? 'Được miễn phí' : 'Chưa chốt phí'}</p>
        {item.fee_ledger_id && <p><a href="#driver-wallet">Xem giao dịch ví #{item.fee_ledger_id}</a></p>}
        {['pending', 'uncertain', 'cancel_pending', 'expiry_release_pending'].includes(item.status) && <p>Chưa có xác nhận cuối từ trụ. Đầu nối vẫn được giữ để tránh đặt trùng.</p>}
        {item.no_show_exempt && <p>Đã ghi nhận miễn phí không đến.</p>}
        {item.can_cancel && <button className="secondary-button" disabled={!!busy || !!error} onClick={() => void cancel(item)}>{busy === item.id ? 'Đang yêu cầu hủy…' : 'Hủy đặt chỗ'}</button>}
      </article>)}
      {result && result.total_pages > 1 && <div className="driver-reservation-pages"><button className="secondary-button" disabled={page <= 1 || !!busy} onClick={() => setPage(page-1)}>Trang trước</button><span>Trang {page}/{result.total_pages}</span><button className="secondary-button" disabled={page >= result.total_pages || !!busy} onClick={() => setPage(page+1)}>Trang sau</button></div>}
      {result && <p className="driver-subtle">Cập nhật {dateLabel(result.generated_at)} · Tự cập nhật mỗi 5 giây. Không thu phí đặt trước; phí không đến dùng mức đã xác nhận lúc đặt.</p>}
    </div>
  </details>
}
