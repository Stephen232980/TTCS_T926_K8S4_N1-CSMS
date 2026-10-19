import { useEffect, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import { DriverInvoicePage } from './DriverInvoicePage'
import { historyDate, historyEnergy, historyLink, historyStates, historyStatus, readHistory, readHistoryRoute, type HistoryPage, type HistoryRoute, type HistorySession, type HistoryState, type SessionDetail } from './driverHistoryApi'

function useHistoryData<T>(path: string, revision: number) {
  const key = `${path}:${revision}`
  const [result, setResult] = useState<{ key: string; data?: T; error?: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void readHistory<T>(path, controller.signal).then(data => {
      if (!controller.signal.aborted) setResult({ key, data })
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setResult({ key, error: cause instanceof Error ? cause.message : 'Không tải được dữ liệu. Vui lòng thử lại.' })
    })
    return () => controller.abort()
  }, [path, key])
  return result?.key === key ? { ...result, loading: false } : { loading: true, data: undefined, error: undefined }
}

function SessionList({ route, navigate }: { route: HistoryRoute; navigate: (route: HistoryRoute) => void }) {
  const [revision, setRevision] = useState(0)
  const { data, error, loading } = useHistoryData<HistoryPage>(`/charging/my-sessions?page=${route.page}&page_size=10&state=${route.state}`, revision)
  return <section className="driver-history-panel" aria-label="Danh sách phiên sạc">
    <div className="driver-history-toolbar">
      <label htmlFor="driver-history-state">Trạng thái<select id="driver-history-state" value={route.state} onChange={event => navigate({ page: 1, state: event.target.value as HistoryState, invoice: false })}>
        {Object.entries(historyStates).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select></label>
      <button type="button" className="secondary-button" disabled={loading} onClick={() => setRevision(value => value + 1)}>Làm mới</button>
    </div>
    {loading && <p role="status">Đang tải lịch sử phiên sạc…</p>}
    {error && <div role="alert"><p>{error}</p><button type="button" className="secondary-button" onClick={() => setRevision(value => value + 1)}>Thử lại</button></div>}
    {data && <>
      <p className="driver-history-count" role="status">{data.total} phiên sạc · Giờ Việt Nam (UTC+7)</p>
      {data.items.length === 0 ? <div className="driver-history-empty">
        <h2>{data.total === 0 ? 'Chưa có phiên sạc phù hợp' : 'Trang này không có phiên sạc'}</h2>
        <p>{route.state === 'all' ? 'Các phiên sạc của bạn sẽ xuất hiện tại đây.' : 'Thử chọn trạng thái khác để xem các phiên còn lại.'}</p>
        {(route.page > 1 || route.state !== 'all') && <button type="button" className="secondary-button" onClick={() => navigate({ page: 1, state: 'all', invoice: false })}>Xem tất cả phiên sạc</button>}
      </div> : <ul className="driver-history-list">{data.items.map(item => <HistoryRow key={item.id} item={item} route={route} navigate={navigate} />)}</ul>}
      {data.total_pages > 1 && <nav className="driver-history-pagination" aria-label="Phân trang lịch sử phiên sạc">
        <button type="button" className="secondary-button" disabled={route.page <= 1} onClick={() => navigate({ ...route, page: route.page - 1 })}><Icon name="chevronLeft" />Trang trước</button>
        <span>Trang {route.page} / {data.total_pages}</span>
        <button type="button" className="secondary-button" disabled={route.page >= data.total_pages} onClick={() => navigate({ ...route, page: route.page + 1 })}>Trang sau<Icon name="chevronRight" /></button>
      </nav>}
    </>}
  </section>
}

function HistoryRow({ item, route, navigate }: { item: HistorySession; route: HistoryRoute; navigate: (route: HistoryRoute) => void }) {
  const energy = item.energy_kwh ?? (!item.ended_at && item.latest_meter_wh !== null ? Math.max(0, Number(item.latest_meter_wh) - Number(item.meter_start_wh)) / 1000 : null)
  const next = { ...route, session: item.id, invoice: false }
  return <li className="driver-history-row">
    <div className="driver-history-location"><a href={historyLink(next)} onClick={event => { event.preventDefault(); navigate(next) }}>Phiên #{item.id} · {item.station_name}</a><span>{item.charge_point_code} · Cổng {item.connector_number}</span></div>
    <div className="driver-history-time"><span>Bắt đầu</span><time dateTime={item.started_at}>{historyDate(item.started_at)}</time></div>
    <div className="driver-history-energy"><span>Điện năng</span><strong>{historyEnergy(energy)}</strong></div>
    <div className="driver-history-state"><span className={`driver-history-badge ${item.ended_at ? 'closed' : item.abnormal_since ? 'abnormal' : 'open'}`}>{historyStatus(item)}</span>{item.review_reasons.length > 0 && <span>Cần kiểm tra</span>}</div>
  </li>
}

function HistoryDetail({ route, navigate }: { route: HistoryRoute; navigate: (route: HistoryRoute) => void }) {
  const [revision, setRevision] = useState(0)
  const { data, error, loading } = useHistoryData<SessionDetail>(`/driver/charging/sessions/${route.session}`, revision)
  return <section className="driver-history-panel" aria-label="Chi tiết phiên sạc">
    <button type="button" className="secondary-button" onClick={() => navigate({ ...route, session: undefined, invoice: false })}><Icon name="chevronLeft" />Quay lại lịch sử</button>
    {loading && <p role="status">Đang tải chi tiết phiên sạc…</p>}
    {error && <div role="alert"><p>{error}</p><button type="button" className="secondary-button" onClick={() => setRevision(value => value + 1)}>Thử lại</button></div>}
    {data && <>
      <h2 className="driver-history-detail-title">Phiên #{data.id}</h2>
      <p className="driver-history-detail-location">{data.station_name} · {data.charge_point_code} · Cổng {data.connector_number}</p>
      <dl className="driver-session-facts">
        <div><dt>Trạng thái</dt><dd>{data.ended_at ? 'Đã kết thúc' : 'Chưa kết thúc'}</dd></div>
        <div><dt>Bắt đầu</dt><dd>{historyDate(data.started_at)}</dd></div>
        <div><dt>Kết thúc</dt><dd>{historyDate(data.ended_at)}</dd></div>
        <div><dt>Điện năng</dt><dd>{historyEnergy(data.energy_kwh)}</dd></div>
        <div><dt>Thời gian sạc</dt><dd>{new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(data.elapsed_seconds / 60)} phút</dd></div>
      </dl>
      {data.awaiting_unplug && <p role="status">Phiên đã dừng, đang chờ rút súng sạc để hoàn tất tính phí.</p>}
      {data.needs_attention && <p role="status">Phiên này cần được kiểm tra. Hóa đơn có thể chưa sẵn sàng.</p>}
      <button type="button" className="primary-button driver-history-invoice" onClick={() => navigate({ ...route, invoice: true })}>Xem hóa đơn phiên này<Icon name="chevronRight" /></button>
    </>}
  </section>
}

export function DriverSessionHistory() {
  const [route, setRoute] = useState(readHistoryRoute)
  useEffect(() => {
    const change = () => setRoute(readHistoryRoute())
    window.addEventListener('popstate', change); window.addEventListener('hashchange', change)
    return () => { window.removeEventListener('popstate', change); window.removeEventListener('hashchange', change) }
  }, [])
  useEffect(() => {
    const main = document.querySelector<HTMLElement>('.driver-main')
    if (main) main.scrollTop = 0
  }, [route.page, route.state, route.session, route.invoice])
  const navigate = (next: HistoryRoute) => {
    window.history.pushState(null, '', historyLink(next))
    setRoute(next)
  }
  if (route.session && route.invoice) return <div className="driver-history-invoice-view">
    <DriverInvoicePage backLabel="Quay lại phiên sạc" key={route.session} sessionId={route.session} onOpen={session => navigate({ ...route, session, invoice: true })} onBack={() => navigate({ ...route, invoice: false })} />
  </div>
  return route.session ? <HistoryDetail route={route} navigate={navigate} /> : <SessionList route={route} navigate={navigate} />
}
