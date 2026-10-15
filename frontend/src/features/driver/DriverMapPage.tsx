import { useEffect, useMemo, useState } from 'react'
import { StationMap, type MapPosition, type MapStation } from '../../components/maps/StationMap'
import { Icon } from '../../components/icons/Icon'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

interface Result { items: MapStation[]; page: number; total: number; total_pages: number }
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
function distance(station: MapStation, position: MapPosition) {
  const rad = (value: number) => value * Math.PI / 180
  const lat = rad(station.latitude - position.latitude), lon = rad(station.longitude - position.longitude)
  const a = Math.sin(lat / 2) ** 2 + Math.cos(rad(position.latitude)) * Math.cos(rad(station.latitude)) * Math.sin(lon / 2) ** 2
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0, 1 - a)))
}
export function DriverMapPage({ selectedStationId, onOpenStation }: { selectedStationId?: string; onOpenStation?: (station: MapStation) => void }) {
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [revision, setRevision] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const [selectedId, setSelectedId] = useState(selectedStationId)
  const [position, setPosition] = useState<MapPosition>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setLoading(true); setError(''); setResult(null)
      async function loadPage(page: number) {
        const response = await fetch(`${base}/api/v1/driver/stations?${new URLSearchParams({ page: String(page), page_size: '100', search: query })}`, { credentials: 'include', signal: controller.signal })
        if (response.status === 401) notifySessionUnauthorized()
        if (!response.ok) throw new Error('Không tải được trạm sạc. Vui lòng thử lại.')
        return await response.json() as Result
      }
      void (async () => {
        try {
          const first = await loadPage(1)
          const items = [...first.items]
          for (let page = 2; page <= first.total_pages; page++) items.push(...(await loadPage(page)).items)
          if (!controller.signal.aborted) { setResult({ ...first, items }); setLoading(false) }
        } catch (cause) {
          if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : 'Không tải được trạm sạc.'); setLoading(false) }
        }
      })()
    }, 0)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [query, revision])
  const stations = useMemo(() => position && result ? [...result.items].sort((a, b) => distance(a, position) - distance(b, position)) : result?.items ?? [], [result, position])
  return <section className="driver-map-page" aria-label="Tìm trạm trên bản đồ">
    <form className="driver-station-search" onSubmit={event => { event.preventDefault(); const next = search.trim(); if (next === query) setRevision(value => value + 1); else setQuery(next) }}>
      <label htmlFor="driver-station-search">Tên trạm hoặc địa chỉ<input id="driver-station-search" type="search" maxLength={100} value={search} onChange={event => setSearch(event.target.value)} placeholder="Bạn muốn sạc ở đâu?" /></label>
      <button className="primary-button" type="submit"><Icon name="search" />Tìm trạm</button>
    </form>
    {loading && <p role="status">Đang tải trạm sạc…</p>}
    {error && <div className="driver-error" role="alert"><p>{error}</p><button className="secondary-button" onClick={() => setRevision(value => value + 1)}>Thử lại</button></div>}
    {!loading && !error && result && <div className="driver-station-layout">
      <div className="driver-map-panel"><StationMap stations={stations} selectedId={selectedId} onSelect={setSelectedId} onLocate={setPosition} userPosition={position} /></div>
      <section className="driver-station-results" aria-label="Danh sách trạm trên bản đồ">
        <div className="driver-results-heading"><h2>{position ? 'Trạm gần bạn' : 'Trạm đang hoạt động'}</h2><span role="status">{stations.length} trạm</span></div>
        <p className="driver-subtle">{position ? 'Sắp theo khoảng cách đường thẳng, không phải quãng đường lái xe.' : 'Bấm “Đến vị trí của tôi” trên bản đồ để sắp trạm gần bạn. Vị trí không gửi lên CSMS.'}</p>
        {stations.length === 0 && <p>Chưa có trạm đang hoạt động phù hợp. Hãy thử tên hoặc địa chỉ khác.</p>}
        {stations.map(station => <article key={station.id} className={`driver-station-card${selectedId === station.id ? ' is-selected' : ''}`}>
          <button type="button" className="driver-station-select" onClick={() => setSelectedId(station.id)} aria-pressed={selectedId === station.id}><Icon name="station" /><span><strong>{station.name}</strong><span>{station.address}</span></span>{position && <span className="driver-distance">{distance(station, position).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} km</span>}</button>
          <div className="driver-station-actions">{onOpenStation && <button className="secondary-button" onClick={() => { setSelectedId(station.id); onOpenStation(station) }}>Xem đầu nối</button>}<a href={`https://www.openstreetmap.org/?mlat=${station.latitude}&mlon=${station.longitude}#map=17/${station.latitude}/${station.longitude}`} target="_blank" rel="noreferrer">Mở vị trí</a></div>
        </article>)}
      </section>
    </div>}
  </section>
}
