import { useEffect, useMemo, useRef, useState } from 'react'
import { StationMap, type MapPosition, type MapStation } from '../../components/maps/StationMap'
import { Icon } from '../../components/icons/Icon'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

export interface DiscoveryStation extends MapStation {
  available_connectors?: number; total_connectors?: number
  energy_rate_vnd_per_kwh?: number | null
  idle_rate_vnd_per_minute?: number | null; grace_minutes?: number | null
  connectors?: { id: string; connector_type: string | null; current_type: string | null; max_power_kw: string | null; available: boolean }[]
}
interface Result { items: DiscoveryStation[]; page: number; total: number; total_pages: number; generated_at?: string; search_too_broad?: boolean }
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
function distance(station: MapStation, position: MapPosition) {
  const rad = (value: number) => value * Math.PI / 180
  const lat = rad(station.latitude - position.latitude), lon = rad(station.longitude - position.longitude)
  const a = Math.sin(lat / 2) ** 2 + Math.cos(rad(position.latitude)) * Math.cos(rad(station.latitude)) * Math.sin(lon / 2) ** 2
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0, 1 - a)))
}
export function DriverMapPage({ selectedStationId, onOpenStation, onStationsUpdated }: { selectedStationId?: string; onOpenStation?: (station: DiscoveryStation) => void; onStationsUpdated?: (stations: DiscoveryStation[]) => void }) {
  const [search, setSearch] = useState('')
  const [mobileMapOpen, setMobileMapOpen] = useState(false)
  const [availableOnly, setAvailableOnly] = useState(false)
  const [connectorType, setConnectorType] = useState('')
  const [query, setQuery] = useState('')
  const [revision, setRevision] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const [selectedId, setSelectedId] = useState(selectedStationId)
  const [position, setPosition] = useState<MapPosition>()
  const [selectionRevision, setSelectionRevision] = useState(0)
  function selectStation(id: string) { setSelectedId(id); setSelectionRevision(value => value + 1) }
  useEffect(() => {
    let active = true
    // Reuse permission already granted; a new permission prompt stays user initiated.
    if (navigator.permissions && navigator.geolocation) {
      void navigator.permissions.query({ name: 'geolocation' }).then(permission => {
        if (active && permission.state === 'granted') navigator.geolocation.getCurrentPosition(
          ({ coords }) => { if (active) setPosition({ latitude: coords.latitude, longitude: coords.longitude }) },
          () => {}, { timeout: 10000, maximumAge: 60000 },
        )
      }).catch(() => {})
    }
    return () => { active = false }
  }, [])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const loadedQuery = useRef(query)
  useEffect(() => {
    if (result && !result.search_too_broad) onStationsUpdated?.(result.items)
  }, [result, onStationsUpdated])
  useEffect(() => {
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running || document.hidden) return
      running = true
      setLoading(true)
      async function loadPage(page: number) {
        const response = await fetch(`${base}/api/v1/driver/stations?${new URLSearchParams({ page: String(page), page_size: '100', search: query })}`, { credentials: 'include', signal: controller.signal })
        if (response.status === 401) notifySessionUnauthorized()
        if (!response.ok) throw new Error('Không tải được trạm sạc. Vui lòng thử lại.')
        return await response.json() as Result
      }
      void (async () => {
        try {
          const first = await loadPage(1)
          if (first.search_too_broad || first.total > 500 || first.total_pages > 5) {
            if (!controller.signal.aborted) { setResult({ ...first, items: [], search_too_broad: true }); setError(''); setLoading(false) }
            return
          }
          const items = [...first.items]
          for (let page = 2; page <= first.total_pages; page++) {
            const next = await loadPage(page)
            if (next.total !== first.total || next.search_too_broad) throw new Error('Danh sách trạm vừa thay đổi. Hãy tải lại để xem đầy đủ.')
            items.push(...next.items)
          }
          const unique = [...new Map(items.map(station => [station.id, station])).values()]
          if (unique.length !== first.total) throw new Error('Danh sách trạm vừa thay đổi. Hãy tải lại để xem đầy đủ.')
          if (!controller.signal.aborted) { setResult({ ...first, items: unique }); setError(''); setLoading(false) }
        } catch (cause) {
          if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : 'Không tải được trạm sạc.'); setLoading(false) }
        }
      })().finally(() => { running = false })
    }
    const timer = window.setTimeout(() => {
      if (loadedQuery.current !== query) { setResult(null); setError(''); loadedQuery.current = query }
      void load()
    }, 0)
    const poll = window.setInterval(() => { void load() }, 15000)
    const visible = () => { if (!document.hidden) void load() }
    document.addEventListener('visibilitychange', visible)
    return () => { window.clearTimeout(timer); window.clearInterval(poll); document.removeEventListener('visibilitychange', visible); controller.abort() }
  }, [query, revision])
  const stations = useMemo(() => position && result ? [...result.items].sort((a, b) => distance(a, position) - distance(b, position) || a.name.localeCompare(b.name, 'vi') || a.id.localeCompare(b.id)) : result?.items ?? [], [result, position])
  const connectorTypes = useMemo(() => [...new Set([
    ...stations.flatMap(station => station.connectors?.map(connector => connector.connector_type?.trim() ?? '') ?? []),
    connectorType,
  ].filter(Boolean))].sort((a, b) => a.localeCompare(b, 'vi')), [stations, connectorType])
  const visibleStations = useMemo(() => stations.filter(station => {
    if (connectorType) return station.connectors?.some(connector => connector.connector_type?.trim() === connectorType && (!availableOnly || connector.available))
    return !availableOnly || (station.available_connectors ?? 0) > 0
  }), [stations, availableOnly, connectorType])
  const hasFilters = availableOnly || !!connectorType
  // Price/status polls must not rebuild markers and reset the user's map view.
  const mapKey = JSON.stringify(visibleStations.map(({ id, name, address, latitude, longitude }) => ({ id, name, address, latitude, longitude })))
  const mapStations = useMemo(() => JSON.parse(mapKey) as MapStation[], [mapKey])
  return <section className="driver-map-page" aria-label="Tìm trạm sạc">
    <form className="driver-station-search" onSubmit={event => { event.preventDefault(); const next = search.trim(); if (next === query) setRevision(value => value + 1); else setQuery(next) }}>
      <label htmlFor="driver-station-search">Tên trạm hoặc địa chỉ<input id="driver-station-search" type="search" maxLength={100} value={search} onChange={event => setSearch(event.target.value)} placeholder="Bạn muốn sạc ở đâu?" /></label>
      <button className="primary-button" type="submit" aria-label="Tìm trạm"><Icon name="search" /><span className="driver-search-button-label">Tìm trạm</span></button>
    </form>
    {loading && <p role="status">Đang tải trạm sạc…</p>}
    {error && <div className="driver-error" role="alert"><p>{error}{result && ' Dữ liệu bên dưới có thể cũ.'}</p><button className="secondary-button" onClick={() => setRevision(value => value + 1)}>Thử lại</button></div>}
    {result?.search_too_broad && <p role="status">Có hơn 500 trạm phù hợp. Nhập tên hoặc địa chỉ cụ thể hơn để xem đầy đủ và sắp theo khoảng cách.</p>}
    {result && !result.search_too_broad && <>
      <div className="driver-discovery-tools">
        <label className="driver-connector-type-filter" htmlFor="driver-connector-type">Loại đầu nối<select id="driver-connector-type" value={connectorType} onChange={event => setConnectorType(event.target.value)}><option value="">Tất cả loại đầu nối</option>{connectorTypes.map(type => <option key={type} value={type}>{type}</option>)}</select></label>
        <label className="driver-availability-filter"><input type="checkbox" checked={availableOnly} onChange={event => setAvailableOnly(event.target.checked)} />Còn đầu nối rảnh</label>
      <button className="secondary-button driver-mobile-map-toggle" type="button" aria-expanded={mobileMapOpen} aria-controls="driver-discovery-map" onClick={() => setMobileMapOpen(value => !value)}>{mobileMapOpen ? 'Ẩn bản đồ' : 'Hiện bản đồ'}</button>
      </div>
      <div className="driver-station-layout">
      <div id="driver-discovery-map" className={`driver-map-panel${mobileMapOpen ? ' is-mobile-open' : ''}`}><StationMap stations={mapStations} selectedId={selectedId} onSelect={selectStation} focusNearby selectionRevision={selectionRevision} onLocate={next => { setSelectedId(undefined); setPosition(next) }} userPosition={position} /></div>
      <section className="driver-station-results" aria-label="Danh sách trạm sạc">
        <div className="driver-results-heading"><h2>{position ? 'Trạm gần bạn' : 'Trạm đang hoạt động'}</h2><span role="status">{hasFilters ? `${visibleStations.length}/${stations.length}` : stations.length} trạm</span></div>
        {stations.length === 0 && <p>Chưa có trạm đang hoạt động phù hợp. Hãy thử tên hoặc địa chỉ khác.</p>}
        {stations.length > 0 && visibleStations.length === 0 && <div className="driver-discovery-empty"><p>{connectorType ? 'Không có trạm phù hợp với bộ lọc đã chọn.' : 'Chưa có trạm còn đầu nối rảnh trong kết quả này.'}</p><button className="secondary-button" onClick={() => { setAvailableOnly(false); setConnectorType('') }}>Xem tất cả trạm</button></div>}
        {visibleStations.map(station => <article key={station.id} className={`driver-station-card${selectedId === station.id ? ' is-selected' : ''}`}>
          <button type="button" className="driver-station-select" onClick={() => selectStation(station.id)} aria-pressed={selectedId === station.id}><Icon name="station" /><span><strong>{station.name}</strong><span>{station.address}</span></span>{position && <span className="driver-distance">{distance(station, position).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} km</span>}</button>
          <div className="driver-discovery-summary">
            <strong>{station.available_connectors ?? 0}/{station.total_connectors ?? 0} đầu nối rảnh</strong>
            <span>{[...new Set(station.connectors?.map(connector => `${connector.connector_type ?? 'Chưa khai báo loại'}${connector.current_type ? ` · ${connector.current_type}` : ''}${connector.max_power_kw ? ` · ${Number(connector.max_power_kw).toLocaleString('vi-VN')} kW` : ''}`))].join('; ') || 'Chưa khai báo đầu nối'}</span>
            <span>{station.energy_rate_vnd_per_kwh == null ? 'Chưa có giá sạc hiện hành' : `${station.energy_rate_vnd_per_kwh.toLocaleString('vi-VN')} đ/kWh`}</span>
            {station.idle_rate_vnd_per_minute != null && <span>Phí chiếm chỗ {station.idle_rate_vnd_per_minute.toLocaleString('vi-VN')} đ/phút · Miễn {station.grace_minutes ?? 0} phút</span>}
          </div>
          <div className="driver-station-actions">{onOpenStation && station.energy_rate_vnd_per_kwh != null && <button className="secondary-button" disabled={!!error || loading} onClick={() => { selectStation(station.id); onOpenStation(station) }}>Xem đầu nối</button>}<a href={`https://www.openstreetmap.org/?mlat=${station.latitude}&mlon=${station.longitude}#map=17/${station.latitude}/${station.longitude}`} target="_blank" rel="noreferrer">Mở vị trí</a></div>
        </article>)}
      </section>
    </div></>}
  </section>
}
