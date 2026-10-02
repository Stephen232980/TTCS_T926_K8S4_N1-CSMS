import { useEffect, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

interface Connection {
  id: string; code: string; station_name: string; connected: boolean; boot_accepted: boolean
  connected_at: string | null; last_boot_at: string | null
  vendor: string | null; model: string | null; firmware_version: string | null
}
interface Result { items: Connection[]; total: number; page: number; total_pages: number }
const time = (value: string | null) => value ? new Date(value).toLocaleString('vi-VN') : 'Chưa có'

export function OcppConnectionsPage() {
  const [result, setResult] = useState<Result | null>(null)
  const [page, setPage] = useState(1)
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  useEffect(() => {
    let stopped = false
    let controller: AbortController | undefined
    async function load() {
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      try {
        const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
        const response = await fetch(`${base}/api/v1/ocpp/connections?page=${page}`, { credentials: 'include', signal })
        if (response.status === 401) notifySessionUnauthorized()
        if (!response.ok) throw new Error(response.status === 403 ? 'Bạn không có quyền xem kết nối trụ.' : 'Không tải được kết nối trụ. Hãy thử lại.')
        const payload = await response.json() as Result
        if (!stopped) { setResult(payload); setError(''); setUpdatedAt(new Date().toISOString()); setLoading(false) }
      } catch (err: unknown) {
        if (!stopped && !signal.aborted) { setError(err instanceof Error ? err.message : 'Không tải được dữ liệu.'); setLoading(false) }
      }
    }
    const first = window.setTimeout(() => { setLoading(true); setResult(null); void load() }, 0)
    const interval = window.setInterval(() => { if (!document.hidden) void load() }, 5000)
    return () => { stopped = true; window.clearTimeout(first); window.clearInterval(interval); controller?.abort() }
  }, [page, revision])
  return <section className="workspace ocpp-workspace" aria-labelledby="page-title">
    <header className="page-heading"><div><h1 id="page-title">Kết nối trụ</h1><p>Xem kết nối hiện tại và thông tin khởi động của trụ.</p></div><button className="secondary-button" onClick={() => setRevision(r => r + 1)}>Làm mới</button></header>
    <p className="ocpp-refresh-note">Tự cập nhật mỗi 5 giây{updatedAt ? ` · Cập nhật lúc ${time(updatedAt)}` : ''}. Trạng thái đầu nối chưa được theo dõi ở màn hình này.</p>
    {loading && <p role="status">Đang tải kết nối trụ…</p>}
    {error && <div className="form-submit-error" role="alert">{error} {result && 'Dữ liệu bên dưới có thể đã cũ.'}<button className="secondary-button" onClick={() => setRevision(r => r + 1)}>Thử lại</button></div>}
    {!loading && !error && result?.items.length === 0 && <p role="status">Chưa có trụ trong phạm vi tài khoản của bạn.</p>}
    {result && result.items.length > 0 && <div className="ocpp-list">
      {result.items.map(connection => <article className="ocpp-row" key={connection.id}>
        <div className="ocpp-row__heading"><div><h2>{connection.code}</h2><p>{connection.station_name}</p></div><span className={`status-badge status-badge--${connection.connected && connection.boot_accepted ? 'active' : connection.connected ? 'suspended' : 'inactive'}`}><span aria-hidden="true" />{connection.connected ? connection.boot_accepted ? 'Đã chấp nhận khởi động' : 'Đã kết nối · Chưa được chấp nhận khởi động' : 'Chưa kết nối'}</span></div>
        <dl className="ocpp-facts"><div><dt>Nhà sản xuất</dt><dd>{connection.vendor ?? 'Chưa có'}</dd></div><div><dt>Mẫu trụ</dt><dd>{connection.model ?? 'Chưa có'}</dd></div><div><dt>Firmware</dt><dd>{connection.firmware_version ?? 'Chưa có'}</dd></div><div><dt>Kết nối từ</dt><dd>{time(connection.connected_at)}</dd></div><div><dt>Khởi động gần nhất</dt><dd>{time(connection.last_boot_at)}</dd></div></dl>
      </article>)}
      {result.total_pages > 1 && <nav className="station-form__actions" aria-label="Phân trang kết nối"><button className="secondary-button" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Trang trước</button><span>Trang {page} / {result.total_pages}</span><button className="secondary-button" disabled={page >= result.total_pages} onClick={() => setPage(p => p + 1)}>Trang sau</button></nav>}
    </div>}
  </section>
}
