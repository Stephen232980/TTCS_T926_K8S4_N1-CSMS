import { useEffect, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'
import { ControlAction } from './ControlAction'
import { ControlAudit } from './ControlAudit'
import { RemoteLogs } from './RemoteLogs'

interface Connector {
  id: string; number: number; status: string; raw_ocpp_status: string | null; status_updated_at: string
  last_error_code: string | null; last_vendor_error_code: string | null; last_error_at: string | null
}
interface Connection {
  id: string; code: string; station_name: string; connected: boolean; boot_accepted: boolean
  connected_at: string | null; last_boot_at: string | null; last_seen_at: string | null; online: boolean
  raw_ocpp_status: string | null; error_code: string | null; vendor_error_code: string | null; error_at: string | null
  vendor: string | null; model: string | null; firmware_version: string | null; connectors: Connector[]
}
interface Result { items: Connection[]; total: number; page: number; total_pages: number }
const time = (value: string | null) => value ? new Date(value).toLocaleString('vi-VN') : 'Chưa có liên lạc'
const statusNames: Record<string, string> = {
  Available: 'Sẵn sàng', Preparing: 'Đang chuẩn bị', Charging: 'Đang sạc', SuspendedEVSE: 'Trụ tạm dừng',
  SuspendedEV: 'Xe tạm dừng', Finishing: 'Đang kết thúc', Reserved: 'Đã đặt trước', Unavailable: 'Không khả dụng', Faulted: 'Có lỗi', unknown: 'Chưa rõ trạng thái',
}
const statusName = (value: string | null) => statusNames[value ?? 'unknown'] ?? value

export function OcppConnectionsPage({ canControl = false, canAudit = false }: { canControl?: boolean; canAudit?: boolean }) {
  const [auditVisible, setAuditVisible] = useState(false)
  const [remoteLogsVisible, setRemoteLogsVisible] = useState(false)
  const [result, setResult] = useState<Result | null>(null)
  const [page, setPage] = useState(1)
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [streamState, setStreamState] = useState('Đang nối luồng cập nhật…')
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  useEffect(() => {
    let stopped = false
    let controller: AbortController | undefined
    let source: EventSource | undefined
    let version = 0
    const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
    const accept = (payload: Result) => { setResult(payload); setError(''); setUpdatedAt(new Date().toISOString()); setLoading(false) }
    async function load() {
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      const issuedVersion = version
      try {
        const response = await fetch(`${base}/api/v1/ocpp/connections?page=${page}&page_size=100`, { credentials: 'include', signal })
        if (response.status === 401) { source?.close(); notifySessionUnauthorized() }
        if (response.status === 403) source?.close()
        if (!response.ok) throw new Error(response.status === 403 ? 'Bạn không có quyền xem kết nối trụ.' : 'Không tải được trạng thái trụ. Hãy thử lại.')
        const payload = await response.json() as Result
        if (!stopped && issuedVersion === version) accept(payload)
      } catch (err: unknown) {
        if (!stopped && !signal.aborted && issuedVersion === version) { setError(err instanceof Error ? err.message : 'Không tải được dữ liệu.'); setLoading(false) }
      }
    }
    const first = window.setTimeout(() => {
      setLoading(true); setResult(null); void load()
      if (typeof EventSource !== 'undefined') {
        source = new EventSource(`${base}/api/v1/ocpp/connections/events?page=${page}&page_size=100`, { withCredentials: true })
        source.onopen = () => { if (!stopped) { setStreamState('Đang cập nhật trực tiếp'); void load() } }
        source.onmessage = event => {
          if (stopped) return
          try { const payload = JSON.parse(event.data) as Result; version++; accept(payload); setStreamState('Đang cập nhật trực tiếp') }
          catch { setStreamState('Không đọc được cập nhật. Đang kết nối lại…'); source?.close(); setRevision(r => r + 1) }
        }
        source.onerror = () => { if (!stopped) { setStreamState('Mất luồng cập nhật · Đang tự kết nối lại. Dữ liệu có thể đã cũ.'); void load() } }
        source.addEventListener('access-denied', () => { source?.close(); notifySessionUnauthorized() })
      } else setStreamState('Tự tải lại mỗi giây')
    }, 0)
    // Fallback for browsers without EventSource; native EventSource handles retries otherwise.
    const fallback = window.setInterval(() => { if (!source && !document.hidden) void load() }, 1000)
    return () => { stopped = true; window.clearTimeout(first); window.clearInterval(fallback); source?.close(); controller?.abort() }
  }, [page, revision])
  const visible = result?.items.filter(c => (!search || `${c.code} ${c.station_name}`.toLocaleLowerCase('vi-VN').includes(search.toLocaleLowerCase('vi-VN'))) && (filter === 'all' || (filter === 'offline' ? !c.online : c.online && (c.raw_ocpp_status === 'Faulted' || c.connectors?.some(k => k.status === 'Faulted'))))) ?? []
  return <section className="workspace ocpp-workspace" aria-labelledby="page-title">
    <header className="page-heading"><div><h1 id="page-title">Giám sát trụ</h1><p>Trạng thái liên lạc và từng đầu nối trong phạm vi quản lý.</p></div><button className="secondary-button" onClick={() => setRevision(r => r + 1)}>Làm mới</button></header>
    <p className="ocpp-refresh-note" role="status">{streamState}{updatedAt ? ` · Cập nhật lúc ${time(updatedAt)}` : ''}</p>
    <div className="ocpp-toolbar"><label>Tìm trong trang<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Mã trụ hoặc tên trạm" /></label><label>Hiển thị<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">Tất cả</option><option value="offline">Ngoại tuyến</option><option value="faulted">Có lỗi</option></select></label><span>{visible.length} / {result?.total ?? 0} trụ</span></div>
    {loading && <p>Đang tải trạng thái trụ…</p>}
    {error && <div className="form-submit-error" role="alert">{error} {result && 'Dữ liệu bên dưới có thể đã cũ.'}<button className="secondary-button" onClick={() => setRevision(r => r + 1)}>Thử lại</button></div>}
    {!loading && !error && result?.items.length === 0 && <p>Chưa có trụ trong phạm vi tài khoản của bạn.</p>}
    {!loading && result && result.items.length > 0 && visible.length === 0 && <p>Không có trụ khớp bộ lọc trong trang này.</p>}
    <div className="ocpp-list">
      {visible.map(connection => <article className="ocpp-row" key={connection.id}>
        {canControl && <ControlAction chargerId={connection.id} label={connection.code} />}
        <div className="ocpp-row__heading"><div><h2>{connection.code}</h2><p>{connection.station_name}</p></div><span className={`status-badge status-badge--${connection.online ? 'active' : 'inactive'}`}><span aria-hidden="true" />{connection.online ? 'Trực tuyến' : 'Ngoại tuyến'}</span></div>
        <dl className="ocpp-facts"><div><dt>Liên lạc cuối</dt><dd>{time(connection.last_seen_at)}</dd></div><div><dt>Trạng thái cả trụ</dt><dd>{statusName(connection.raw_ocpp_status)}</dd></div><div><dt>Nhà sản xuất / mẫu trụ</dt><dd>{connection.vendor ?? 'Chưa có'} / {connection.model ?? 'Chưa có'}</dd></div><div><dt>Khởi động gần nhất</dt><dd>{time(connection.last_boot_at)}</dd></div></dl>
        {connection.error_code && connection.error_code !== 'NoError' && <p className="ocpp-error">Lỗi trụ: {connection.error_code}{connection.vendor_error_code ? ` · ${connection.vendor_error_code}` : ''} · {time(connection.error_at)}</p>}
        {connection.connectors?.length ? <ul className="ocpp-connectors" aria-label={`Đầu nối ${connection.code}`}>
          {connection.connectors.map(connector => <li key={connector.id}><div className="ocpp-connector-heading"><strong>Đầu nối {connector.number}</strong><span className={`status-badge status-badge--${connector.status === 'Faulted' ? 'blocked' : connector.status === 'Available' ? 'active' : 'inactive'}`}>{statusName(connector.status)}</span></div><p>Cập nhật trạng thái: {time(connector.status_updated_at)}</p>{connector.last_error_code && <p className="ocpp-error">Lỗi gần nhất: {connector.last_error_code}{connector.last_vendor_error_code ? ` · ${connector.last_vendor_error_code}` : ''} · {time(connector.last_error_at)}</p>}</li>)}
        </ul> : <p className="ocpp-refresh-note">Chưa khai báo đầu nối.</p>}
        <details className="ocpp-details"><summary>Thông tin kết nối và khởi động</summary><p>{connection.connected ? 'Socket đang kết nối' : 'Socket chưa kết nối'} · {connection.boot_accepted ? 'Đã chấp nhận khởi động' : 'Chưa được chấp nhận khởi động'} · Firmware {connection.firmware_version ?? 'Chưa có'}</p><p>Kết nối từ: {time(connection.connected_at)}</p></details>
      </article>)}
    </div>
    {canAudit && (
      <>
        <button className="secondary-button" aria-expanded={auditVisible} onClick={() => setAuditVisible(value => !value)}>Nhật ký điều khiển cũ</button>
        {auditVisible && <ControlAudit />}
        <button className="secondary-button" aria-expanded={remoteLogsVisible} onClick={() => setRemoteLogsVisible(value => !value)} style={{ marginLeft: '1rem' }}>Nhật ký lệnh từ xa</button>
        {remoteLogsVisible && <RemoteLogs />}
      </>
    )}
    {result && result.total_pages > 1 && <nav className="station-form__actions" aria-label="Phân trang kết nối"><button className="secondary-button" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Trang trước</button><span>Trang {page} / {result.total_pages}</span><button className="secondary-button" disabled={page >= result.total_pages} onClick={() => setPage(p => p + 1)}>Trang sau</button></nav>}
  </section>
}
