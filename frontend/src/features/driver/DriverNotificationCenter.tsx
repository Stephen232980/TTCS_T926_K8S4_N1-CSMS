import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import { notifySessionUnauthorized } from '../auth/sessionEvents'
import { DriverNotificationToastContainer } from './DriverNotificationToast'
import { emitBrowserNotification, type DriverNotificationItem } from './driverNotificationService'

interface InboxItem { id: string; session_id: number; event_type: 'stop' | 'idle' | 'invoice'; title: string; message: string; occurred_at: string; created_at: string; read_at: string | null }
function readableMessage(message: string) {
  return message.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, value => {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' })
  })
}
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
export function DriverNotificationCenter({ ownerId, open, onOpenChange }: { ownerId: string; open?: boolean; onOpenChange?: (open: boolean) => void }) {
  const [localOpen, setLocalOpen] = useState(false)
  const expanded = open ?? localOpen
  const setExpanded = (value: boolean) => { if (onOpenChange) onOpenChange(value); else setLocalOpen(value) }
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null)
  const contentId = useId()
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  useEffect(() => {
    if (!expanded) return
    const outside = (event: PointerEvent) => { if (event.target instanceof Node && !root.current?.contains(event.target)) { if (onOpenChange) onOpenChange(false); else setLocalOpen(false) } }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { if (onOpenChange) onOpenChange(false); else setLocalOpen(false); trigger.current?.focus({ preventScroll: true }) } }
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [expanded, onOpenChange])
  const [items, setItems] = useState<InboxItem[]>([])
  const [toasts, setToasts] = useState<DriverNotificationItem[]>([])
  const [error, setError] = useState('')
  const [permission, setPermission] = useState<NotificationPermission>(() => typeof Notification === 'undefined' ? 'denied' : Notification.permission)
  const [cursor, setCursor] = useState<string | null>(null)
  const seen = useRef(new Set<string>())
  const dismiss = useCallback((id: string) => setToasts(previous => previous.filter(item => item.id !== id)), [])
  useEffect(() => {
    let stopped = false
    let timer: number | undefined
    let denied = false
    const controller = new AbortController()
    async function poll() {
      try {
        const response = await fetch(`${base}/api/v1/driver/notifications`, { credentials: 'include', signal: controller.signal })
        if (response.status === 401 || response.status === 403) { denied = true; setItems([]); setToasts([]); notifySessionUnauthorized(); return }
        if (!response.ok) throw new Error('inbox')
        const data = await response.json() as { items: InboxItem[]; next_cursor: string | null }
        if (stopped) return
        if (!Array.isArray(data.items) || data.items.some(item => typeof item.id !== 'string' || typeof item.title !== 'string' || typeof item.message !== 'string')) throw new Error('inbox')
        const fresh = data.items.filter(item => !item.read_at && !seen.current.has(item.id))
        data.items.forEach(item => seen.current.add(item.id))
        setItems(previous => [...data.items, ...previous.filter(item => !data.items.some(fresh => fresh.id === item.id))])
        setCursor(previous => previous ?? data.next_cursor)
        setError('')
        if (fresh.length) {
          const display = fresh.slice(0, 5).map(item => ({ id: item.id, sessionId: item.session_id, type: item.event_type, title: item.title, message: item.message, createdAt: Date.now(), ...(item.event_type === 'invoice' ? { actionHref: `#driver-invoice-${item.session_id}`, actionLabel: 'Xem hóa đơn' } : {}) }))
          setToasts(previous => [...display, ...previous].slice(0, 5))
          display.forEach(item => emitBrowserNotification(item.title, { body: item.message, tag: item.id }))
        }
      } catch { if (!stopped && !controller.signal.aborted) setError('Chưa cập nhật được thông báo. Đang thử lại.') }
      finally { if (!stopped) setLoading(false); if (!stopped && !denied) timer = window.setTimeout(() => { void poll() }, 2000) }
    }
    void poll()
    return () => { stopped = true; controller.abort(); window.clearTimeout(timer) }
  }, [ownerId])
  async function markRead(id: string) {
    if (busy) return
    setBusy(id)
    try {
      const response = await fetch(`${base}/api/v1/driver/notifications/${id}/read`, { method: 'POST', credentials: 'include' })
      if (!response.ok) throw new Error('read')
      const item = await response.json() as InboxItem
      setItems(previous => previous.map(row => row.id === id ? item : row))
    } catch { setError('Chưa đánh dấu đã đọc được. Vui lòng thử lại.') } finally { setBusy('') }
  }
  async function older() {
    if (!cursor || busy) return
    setBusy('older')
    try {
      const response = await fetch(`${base}/api/v1/driver/notifications?before=${encodeURIComponent(cursor)}`, { credentials: 'include' })
      if (!response.ok) throw new Error('inbox')
      const data = await response.json() as { items: InboxItem[]; next_cursor: string | null }
      setItems(previous => [...previous, ...data.items.filter(row => !previous.some(old => old.id === row.id))])
      setCursor(data.next_cursor)
    } catch { setError('Chưa tải được thông báo cũ. Vui lòng thử lại.') } finally { setBusy('') }
  }
  const unread = items.filter(item => !item.read_at).length
  return <div className="driver-notification-control" ref={root}>
    <DriverNotificationToastContainer notifications={toasts} onDismiss={dismiss} />
    <button ref={trigger} type="button" className="secondary-button driver-notification-trigger" aria-label={`Thông báo${unread ? ` · ${unread} chưa đọc` : ''}`} aria-expanded={expanded} aria-controls={contentId} onClick={() => setExpanded(!expanded)}>
      <Icon name="bell" />{unread > 0 && <span className="driver-unread-count" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
    </button>
    {expanded && <section id={contentId} className="driver-inbox-popover" aria-label="Danh sách thông báo">
      <div className="driver-popover-heading"><div><h2>Thông báo</h2><span>{unread ? `${unread} chưa đọc` : 'Bạn đã xem hết thông báo'}</span></div><button type="button" className="secondary-button" aria-label="Đóng danh sách thông báo" onClick={() => { setExpanded(false); trigger.current?.focus({ preventScroll: true }) }}><Icon name="close" /></button></div>
      {error && <p role="status">{error}</p>}
      {loading && <p role="status">Đang tải thông báo…</p>}
      {!loading && !error && !items.length && <p>Chưa có thông báo phiên sạc.</p>}
      {typeof Notification !== 'undefined' && permission === 'default' && <button type="button" className="secondary-button" onClick={() => { void Notification.requestPermission().then(setPermission).catch(() => setError('Chưa bật được thông báo trình duyệt.')) }}>Bật thông báo trình duyệt</button>}
      <ul className="driver-inbox-items">{items.map(item => <li className={item.read_at ? '' : 'is-unread'} key={item.id}>
        <div className="driver-inbox-item-heading"><Icon name={item.event_type === 'invoice' ? 'report' : 'charger'} /><strong>{item.title}</strong>{!item.read_at && <span className="driver-unread-dot" aria-label="Chưa đọc" />}</div>
        <time dateTime={item.occurred_at}>{new Date(item.occurred_at).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' })}</time>
        <p>{readableMessage(item.message)}</p>
        <div className="driver-inbox-item-actions">{item.event_type === 'invoice' && <a href={`#driver-invoice-${item.session_id}`} onClick={() => setExpanded(false)}>Xem hóa đơn</a>}
        {!item.read_at && <button type="button" className="secondary-button" disabled={!!busy} onClick={() => { void markRead(item.id) }}>Đánh dấu đã đọc</button>}</div>
      </li>)}</ul>
      {cursor && <button type="button" className="secondary-button" disabled={!!busy} onClick={() => { void older() }}>{busy === 'older' ? 'Đang tải…' : 'Xem thông báo cũ'}</button>}
    </section>}
  </div>
}
