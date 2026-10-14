import { useEffect, useRef, useState } from 'react'
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
  const [data, setData] = useState<AlertPage>()
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [page, setPage] = useState(1)
  const [history, setHistory] = useState(false)
  const [revision, setRevision] = useState(0)
  const [reason, setReason] = useState('')
  const [closing, setClosing] = useState('')
  const generation = useRef(0)
  const reasonInput = useRef<HTMLInputElement>(null)
  const path = `/${area}/alerts`
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
          setPage(result.page)
          setError('')
        }
      } catch {
        if (!controller.signal.aborted) setError('Chưa cập nhật được cảnh báo. Dữ liệu đang hiển thị có thể đã cũ.')
      } finally { running = false }
    }
    void load()
    const timer = setInterval(() => void load(), 10000)
    const visible = () => { if (document.visibilityState !== 'hidden') void load() }
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
  return <section className="csms-alerts" aria-label="Cảnh báo trụ">
    <div className="csms-alerts-heading">
      <h2>Cảnh báo trụ {data && <span>({data.total})</span>}</h2>
      <div className="csms-alerts-actions">
        <button type="button" disabled={!!busy} onClick={() => { setHistory(!history); setPage(1); setData(undefined); setClosing(''); setNotice('') }}>{history ? 'Cảnh báo đang mở' : 'Lịch sử cảnh báo'}</button>
        <button type="button" disabled={!!busy} onClick={() => setRevision(value => value + 1)}>Tải lại cảnh báo</button>
      </div>
    </div>
    {error && <p role="alert">{error}</p>}
    {actionError && <p role="alert">{actionError}</p>}
    {notice && <p role="status">{notice}</p>}
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
    {data && <p className="csms-alerts-muted">Cập nhật {new Date(data.generated_at).toLocaleTimeString('vi-VN')} · Tự cập nhật mỗi 10 giây. Cảnh báo không thay thế trạng thái trực tuyến của trụ.</p>}
  </section>
}
