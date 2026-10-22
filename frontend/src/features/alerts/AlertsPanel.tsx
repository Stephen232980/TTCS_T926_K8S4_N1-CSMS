import { useEffect, useId, useRef, useState } from 'react'
import { ownerRequest } from '../owner/ownerApi'
import './alerts.css'

interface AlertItem {
  id: string
  charge_point_code: string
  station_name: string
  kind: 'offline' | 'error_burst'
  status: 'open' | 'acknowledged' | 'closed'
  opened_at: string
  recovered_at: string | null
  close_reason: string | null
  email_status: string
  email_attempts: number
}
interface AlertPage {
  items: AlertItem[]
  total: number
  page: number
  total_pages: number
  generated_at: string
}
const emailLabels: Record<string, string> = {
  unconfigured: 'Email chưa cấu hình', pending: 'Email đang chờ', retry: 'Email đang thử lại',
  failed: 'Email gửi thất bại', sent: 'Email đã gửi',
}
const stateLabels = { open: 'Chưa xử lý', acknowledged: 'Đã tiếp nhận', closed: 'Đã đóng' }

export function AlertsPanel({ area }: { area: 'ops' | 'owner' | 'admin' }) {
  const contentId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const sectionRef = useRef<HTMLElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [data, setData] = useState<AlertPage>()
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [page, setPage] = useState(1)
  const [history, setHistory] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [totals, setTotals] = useState<{ active?: number; closed?: number }>({})
  const [revision, setRevision] = useState(0)
  const [reason, setReason] = useState('')
  const [closing, setClosing] = useState('')
  const generation = useRef(0)
  const reasonInput = useRef<HTMLInputElement>(null)
  const path = `/${area}/alerts`
  function dismiss(restoreFocus = false) {
    setExpanded(false)
    setClosing('')
    if (restoreFocus) triggerRef.current?.focus({ preventScroll: true })
  }
  useEffect(() => {
    if (!expanded) return
    panelRef.current?.focus({ preventScroll: true })
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setExpanded(false)
        setClosing('')
        triggerRef.current?.focus({ preventScroll: true })
      }
    }
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !sectionRef.current?.contains(event.target)) {
        setExpanded(false)
        setClosing('')
      }
    }
    document.addEventListener('keydown', escape)
    document.addEventListener('pointerdown', outside)
    return () => {
      document.removeEventListener('keydown', escape)
      document.removeEventListener('pointerdown', outside)
    }
  }, [expanded])
  useEffect(() => {
    if (closing) {
      reasonInput.current?.focus()
      reasonInput.current?.scrollIntoView?.({ block: 'nearest' })
    }
  }, [closing])
  useEffect(() => {
    const controller = new AbortController()
    const current = ++generation.current
    let running = false
    async function load() {
      if (running || document.visibilityState === 'hidden') return
      running = true
      try {
        const result = await ownerRequest<AlertPage>(`${path}?status=${history ? 'closed' : 'active'}&page=${page}`, { signal: controller.signal })
        if (!controller.signal.aborted && current === generation.current) {
          setData(result)
          setTotals(value => ({ ...value, [history ? 'closed' : 'active']: result.total }))
          setPage(result.page)
          setError('')
        }
      } catch {
        if (!controller.signal.aborted && current === generation.current) setError('Chưa cập nhật được cảnh báo. Dữ liệu đang hiển thị có thể đã cũ.')
      } finally { running = false }
    }
    async function loadOtherTotal() {
      if (document.visibilityState === 'hidden') return
      try {
        const other = await ownerRequest<AlertPage>(`${path}?status=${history ? 'active' : 'closed'}&page=1`, { signal: controller.signal })
        if (!controller.signal.aborted && current === generation.current) setTotals(value => ({ ...value, [history ? 'active' : 'closed']: other.total }))
      } catch {
        if (!controller.signal.aborted && current === generation.current) setTotals(value => ({ ...value, [history ? 'active' : 'closed']: undefined }))
      }
    }
    void load()
    void loadOtherTotal()
    const timer = setInterval(() => { void load(); void loadOtherTotal() }, 10000)
    const visible = () => { if (document.visibilityState !== 'hidden') { void load(); void loadOtherTotal() } }
    document.addEventListener('visibilitychange', visible)
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener('visibilitychange', visible) }
  }, [path, page, history, revision])

  async function act(id: string, action: string, force = false) {
    if (busy) return
    setBusy(id)
    setActionError('')
    setNotice('')
    // Invalidate polling issued before a mutation, without losing the displayed list.
    generation.current += 1
    try {
      await ownerRequest(`${path}/${id}/${action}`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: action === 'close' ? JSON.stringify({ force, reason }) : undefined })
      setNotice(action === 'acknowledge' ? 'Đã tiếp nhận cảnh báo.' : action === 'close' ? 'Đã đóng cảnh báo.' : 'Đã yêu cầu thử lại email.')
      setClosing('')
      setReason('')
    } catch {
      setActionError(action === 'close' ? 'Chưa đóng được. Trụ cần phục hồi trước khi đóng; quản trị viên có thể đóng kèm lý do.' : 'Chưa thực hiện được. Hãy tải lại cảnh báo rồi thử lại.')
    } finally {
      setBusy('')
      setRevision(value => value + 1)
    }
  }
  return <section ref={sectionRef} className={`csms-alerts${expanded ? ' is-expanded' : ''}`} aria-label="Cảnh báo trụ">
    <div className="csms-alerts-heading">
      <h2>Cảnh báo trụ</h2>
      <span className="csms-alerts-count">Đang mở: {totals.active ?? '…'} · Đã đóng: {totals.closed ?? '…'}</span>
      <div className="csms-alerts-actions">
        {([false, true] as const).map(showHistory => <button key={String(showHistory)} type="button"
          aria-expanded={expanded && history === showHistory} aria-controls={contentId} disabled={!!busy}
          onClick={event => {
            triggerRef.current = event.currentTarget
            if (expanded && history === showHistory) { dismiss(); return }
            if (history !== showHistory) { setData(undefined); setError('') }
            setHistory(showHistory); setPage(1); setExpanded(true); setClosing(''); setNotice(''); setActionError('')
          }}>{showHistory ? 'Lịch sử' : 'Đang mở'} ({totals[showHistory ? 'closed' : 'active'] ?? '…'})</button>)}
      </div>
    </div>
    {error && <p role="alert">{error}</p>}
    {actionError && <p role="alert">{actionError}</p>}
    {notice && <p role="status">{notice}</p>}
    <div ref={panelRef} id={contentId} className="csms-alerts-popover" role="region" aria-label={history ? 'Lịch sử cảnh báo' : 'Cảnh báo đang mở'} tabIndex={-1} hidden={!expanded}>
      <div className="csms-alerts-popover-heading">
        <h3>{history ? 'Lịch sử cảnh báo' : 'Cảnh báo đang mở'}</h3>
        <button type="button" aria-label="Đóng danh sách cảnh báo" onClick={() => dismiss(true)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg></button>
      </div>
    {error && <button type="button" disabled={!!busy} onClick={() => setRevision(value => value + 1)}>Thử lại</button>}
    {!data && !error && <p role="status">Đang tải cảnh báo…</p>}
    {data && !data.items.length && <p className="csms-alerts-muted">{history ? 'Chưa có cảnh báo đã đóng.' : 'Không có cảnh báo đang mở.'}</p>}
    {data && <ul className="csms-alerts-list">{data.items.map(item => <li key={item.id}>
      <div className="csms-alerts-details">
        <strong>{item.charge_point_code} · {item.kind === 'offline' ? 'Ngoại tuyến quá ngưỡng' : 'Lỗi đầu nối liên tục'}</strong>
        <span>{item.station_name} · {stateLabels[item.status]}{item.recovered_at && item.status !== 'closed' ? ' · Đã phục hồi' : ''}</span>
        <span>Mở lúc {new Date(item.opened_at).toLocaleString('vi-VN')} · {emailLabels[item.email_status] ?? 'Email đang xử lý'}</span>
        {item.close_reason && <span>Lý do đóng: {item.close_reason === 'recovered' ? 'Trụ đã phục hồi' : item.close_reason}</span>}
      </div>
      {area !== 'owner' && <div className="csms-alerts-actions">
        {item.status === 'open' && <button type="button" disabled={!!busy} onClick={() => void act(item.id, 'acknowledge')}>Tiếp nhận {item.charge_point_code}</button>}
        {item.email_status === 'failed' && <button type="button" disabled={!!busy} onClick={() => void act(item.id, 'retry-email')}>Thử lại email {item.charge_point_code}</button>}
        {item.status !== 'closed' && (item.recovered_at || area === 'admin') && <button type="button" disabled={!!busy} onClick={() => { setClosing(item.id); setReason(''); setActionError('') }}>Đóng {item.charge_point_code}</button>}
      </div>}
      {closing === item.id && <form className="csms-alerts-close" onSubmit={event => { event.preventDefault(); void act(item.id, 'close', area === 'admin' && !item.recovered_at) }}>
        <label>Lý do đóng {item.charge_point_code}<input ref={reasonInput} value={reason} maxLength={500} required={area === 'admin' && !item.recovered_at} disabled={!!busy} onChange={event => setReason(event.target.value)} /></label>
        <div className="csms-alerts-actions"><button type="submit" disabled={!!busy}>Xác nhận đóng</button><button type="button" disabled={!!busy} onClick={() => setClosing('')}>Hủy</button></div>
      </form>}
    </li>)}</ul>}
    {data && data.total_pages > 1 && <div className="csms-alerts-actions"><button disabled={page === 1 || !!busy} onClick={() => { setPage(page - 1); setData(undefined) }}>Trang trước</button><span>Trang {page}/{data.total_pages}</span><button disabled={page >= data.total_pages || !!busy} onClick={() => { setPage(page + 1); setData(undefined) }}>Trang sau</button></div>}
    {data && <p className="csms-alerts-muted">Cập nhật {new Date(data.generated_at).toLocaleTimeString('vi-VN')}</p>}
    </div>
  </section>
}
