import { useCallback, useEffect, useRef, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'
import { DriverNotificationToastContainer } from './DriverNotificationToast'
import { emitBrowserNotification, type DriverNotificationItem } from './driverNotificationService'

interface InboxItem { id: string; session_id: number; event_type: 'stop' | 'idle' | 'invoice'; title: string; message: string; occurred_at: string; created_at: string; read_at: string | null }
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
export function DriverNotificationCenter({ ownerId }: { ownerId: string }) {
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
      finally { if (!stopped && !denied) timer = window.setTimeout(() => { void poll() }, 2000) }
    }
    void poll()
    return () => { stopped = true; controller.abort(); window.clearTimeout(timer) }
  }, [ownerId])
  async function markRead(id: string) {
    try {
      const response = await fetch(`${base}/api/v1/driver/notifications/${id}/read`, { method: 'POST', credentials: 'include' })
      if (!response.ok) throw new Error('read')
      const item = await response.json() as InboxItem
      setItems(previous => previous.map(row => row.id === id ? item : row))
    } catch { setError('Chưa đánh dấu đã đọc được. Vui lòng thử lại.') }
  }
  async function older() {
    if (!cursor) return
    try {
      const response = await fetch(`${base}/api/v1/driver/notifications?before=${encodeURIComponent(cursor)}`, { credentials: 'include' })
      if (!response.ok) throw new Error('inbox')
      const data = await response.json() as { items: InboxItem[]; next_cursor: string | null }
      setItems(previous => [...previous, ...data.items.filter(row => !previous.some(old => old.id === row.id))])
      setCursor(data.next_cursor)
    } catch { setError('Chưa tải được thông báo cũ. Vui lòng thử lại.') }
  }
  return <>
    <DriverNotificationToastContainer notifications={toasts} onDismiss={dismiss} />
    <details className="driver-inbox">
      <summary>Thông báo{items.some(item => !item.read_at) ? ` · ${items.filter(item => !item.read_at).length} chưa đọc` : ''}</summary>
      {error && <p role="status">{error}</p>}
      {!items.length && <p>Chưa có thông báo phiên sạc.</p>}
      {typeof Notification !== 'undefined' && permission === 'default' && <button type="button" className="secondary-button" onClick={() => { void Notification.requestPermission().then(setPermission).catch(() => setError('Chưa bật được thông báo trình duyệt.')) }}>Bật thông báo trình duyệt</button>}
      <ul>{items.map(item => <li key={item.id}>
        <strong>{item.title}</strong><p>{item.message}</p>
        {item.event_type === 'invoice' && <a href={`#driver-invoice-${item.session_id}`}>Xem hóa đơn</a>}
        {!item.read_at && <button type="button" className="secondary-button" onClick={() => { void markRead(item.id) }}>Đánh dấu đã đọc</button>}
      </li>)}</ul>
      {cursor && <button type="button" className="secondary-button" onClick={() => { void older() }}>Xem thông báo cũ</button>}
    </details>
  </>
}
