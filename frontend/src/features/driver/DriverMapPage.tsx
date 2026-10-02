import { useEffect, useState } from 'react'
import { StationMap, type MapStation } from '../../components/maps/StationMap'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

interface Result { items: MapStation[]; page: number; total: number; total_pages: number }
export function DriverMapPage() {
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [revision, setRevision] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const [selectedId, setSelectedId] = useState<string>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setLoading(true); setError(''); setResult(null)
      const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
      fetch(`${base}/api/v1/driver/stations?${new URLSearchParams({ page: String(page), search: query })}`, { credentials: 'include', signal: controller.signal })
        .then(async response => {
          if (response.status === 401) notifySessionUnauthorized()
          if (!response.ok) throw new Error('Không tải được trạm sạc. Vui lòng thử lại.')
          return await response.json() as Result
        }).then(data => { setResult(data); setLoading(false) })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return
          setError(err instanceof Error ? err.message : 'Không tải được trạm sạc.'); setLoading(false)
        })
    }, 0)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [query, page, revision])
  return <section className="workspace driver-map-page" aria-labelledby="page-title">
    <header className="page-heading"><div><h1 id="page-title">Tìm trạm sạc</h1><p>Xem vị trí các trạm đang hoạt động và chọn trạm trên bản đồ.</p></div></header>
    <form className="driver-map-search" onSubmit={e => { e.preventDefault(); setQuery(search.trim()); setPage(1) }}>
      <label htmlFor="driver-station-search">Tên trạm hoặc địa chỉ</label>
      <input id="driver-station-search" type="search" maxLength={100} value={search} onChange={e => setSearch(e.target.value)} placeholder="Nhập khu vực bạn muốn tìm" />
      <button className="primary-button" type="submit">Tìm trạm</button>
    </form>
    {loading && <p role="status">Đang tải trạm sạc…</p>}
    {error && <div role="alert"><p>{error}</p><button className="secondary-button" onClick={() => setRevision(r => r + 1)}>Thử lại</button></div>}
    {!loading && !error && result && <>
      <p role="status">{result.total ? `${result.total} trạm đang hoạt động. Bản đồ hiển thị các trạm trên trang ${page}.` : 'Chưa có trạm đang hoạt động phù hợp. Hãy thử tên hoặc địa chỉ khác.'}</p>
      <div className="driver-map-layout">
        <StationMap stations={result.items} selectedId={selectedId} onSelect={setSelectedId} />
        <div className="driver-map-list" aria-label="Danh sách trạm trên bản đồ">
          {result.items.map(station => <article key={station.id} className={selectedId === station.id ? 'driver-map-station driver-map-station--selected' : 'driver-map-station'}>
            <button type="button" className="station-name-button" onClick={() => setSelectedId(station.id)} aria-pressed={selectedId === station.id}><strong>{station.name}</strong></button>
            <p>{station.address}</p>
            <a href={`https://www.openstreetmap.org/?mlat=${station.latitude}&mlon=${station.longitude}#map=17/${station.latitude}/${station.longitude}`} target="_blank" rel="noreferrer">Mở vị trí trên bản đồ</a>
          </article>)}
        </div>
      </div>
      {result.total_pages > 1 && <div className="station-form__actions"><button className="secondary-button" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Trang trước</button><span>Trang {page} / {result.total_pages}</span><button className="secondary-button" disabled={page >= result.total_pages} onClick={() => setPage(p => p + 1)}>Trang sau</button></div>}
    </>}
  </section>
}
