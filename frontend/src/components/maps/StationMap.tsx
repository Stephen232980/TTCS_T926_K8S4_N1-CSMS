import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

export interface MapPosition { latitude: number; longitude: number }
export interface MapStation extends MapPosition { id: string; name: string; address: string }
interface Props {
  stations?: MapStation[]
  position?: MapPosition
  onPick?: (position: MapPosition) => void
  selectedId?: string
  onSelect?: (id: string) => void
  disabled?: boolean
}
const emptyStations: MapStation[] = []
const markerIcon = L.divIcon({ className: 'station-map-pin', html: '<span></span>', iconSize: [24, 24], iconAnchor: [12, 12] })

export function StationMap({ stations = emptyStations, position, onPick, selectedId, onSelect, disabled = false }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const callbacks = useRef({ onPick, onSelect, disabled })
  const [tileError, setTileError] = useState(false)
  const [locationError, setLocationError] = useState('')
  const [locating, setLocating] = useState(false)
  useEffect(() => { callbacks.current = { onPick, onSelect, disabled } }, [onPick, onSelect, disabled])

  useEffect(() => {
    if (!container.current) return
    const instance = L.map(container.current, { scrollWheelZoom: false }).setView([16.1, 106.2], 5)
    map.current = instance
    const tiles = L.tileLayer(import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: import.meta.env.VITE_MAP_ATTRIBUTION || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(instance)
    tiles.on('tileerror', () => setTileError(true))
    instance.on('click', (event: L.LeafletMouseEvent) => {
      if (!callbacks.current.disabled) callbacks.current.onPick?.({ latitude: event.latlng.lat, longitude: event.latlng.lng })
    })
    const observer = new ResizeObserver(() => instance.invalidateSize())
    observer.observe(container.current)
    return () => { observer.disconnect(); instance.remove(); map.current = null }
  }, [])

  useEffect(() => {
    const instance = map.current
    if (!instance) return
    const markers = L.layerGroup().addTo(instance)
    let selectedMarker: L.Marker | undefined
    for (const station of stations) {
      const content = document.createElement('div')
      const title = document.createElement('strong')
      title.textContent = station.name
      const address = document.createElement('p')
      address.textContent = station.address
      content.append(title, address)
      const marker = L.marker([station.latitude, station.longitude], { icon: markerIcon, title: station.name }).bindPopup(content).addTo(markers)
      marker.on('click', () => callbacks.current.onSelect?.(station.id))
      if (station.id === selectedId) selectedMarker = marker
    }
    if (position) {
      L.marker([position.latitude, position.longitude], { icon: markerIcon, title: 'Vị trí trạm đã chọn' }).addTo(markers)
      instance.setView([position.latitude, position.longitude], Math.max(instance.getZoom(), 15))
    } else if (stations.length) {
      instance.fitBounds(L.latLngBounds(stations.map(s => [s.latitude, s.longitude])), { padding: [35, 35], maxZoom: 15 })
    }
    selectedMarker?.openPopup()
    return () => { markers.remove() }
  }, [stations, position, selectedId])

  function locate() {
    if (locating) return
    if (!navigator.geolocation) { setLocationError('Trình duyệt không hỗ trợ định vị. Bạn có thể di chuyển bản đồ để chọn trạm.'); return }
    setLocationError('')
    setLocating(true)
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      if (!map.current) return
      setLocating(false)
      map.current?.setView([coords.latitude, coords.longitude], 15)
    }, error => {
      if (!map.current) return
      setLocating(false)
      const messages: Record<number, string> = {
        1: 'Quyền định vị bị chặn. Hãy kiểm tra quyền vị trí của trình duyệt và thiết bị.',
        2: 'Thiết bị chưa cung cấp được vị trí hiện tại. Bạn có thể thử lại hoặc di chuyển bản đồ.',
        3: 'Hết thời gian chờ vị trí. Bạn có thể thử lại hoặc di chuyển bản đồ; không cần cấp lại quyền nếu đã cho phép.',
      }
      setLocationError(messages[error.code] ?? 'Không lấy được vị trí. Bạn có thể thử lại hoặc di chuyển bản đồ.')
    }, { timeout: 30000, maximumAge: 60000 })
  }

  return <div className="station-map">
    <div className="station-map__tools">
      <button type="button" className="secondary-button" onClick={locate} disabled={disabled || locating}>{locating ? 'Đang lấy vị trí…' : 'Đến vị trí của tôi'}</button>
      {onPick && <button type="button" className="secondary-button" disabled={disabled} onClick={() => {
        const center = map.current?.getCenter()
        if (center) onPick({ latitude: center.lat, longitude: center.lng })
      }}>Chọn tâm bản đồ</button>}
    </div>
    <div ref={container} className="station-map__canvas" role="region" aria-label={onPick ? 'Chọn vị trí trạm trên bản đồ' : 'Bản đồ trạm sạc'} />
    {tileError && <p role="status">Không tải được nền bản đồ. Hãy kiểm tra kết nối mạng và tải lại trang.</p>}
    {locationError && <p role="status">{locationError}</p>}
  </div>
}
