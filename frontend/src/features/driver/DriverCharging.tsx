import { useEffect, useRef, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'
import { ChargerDrawing, ConnectorSymbol } from '../owner/OwnerVisuals'
import { Icon } from '../../components/icons/Icon'

interface StartResult { id: string; status: string; deadline: string | null; session_id?: number | null }
interface Session { id: number; station_name: string; charge_point_code: string; connector_number: number; started_at: string; energy_kwh: string | number; elapsed_seconds: number; latest_meter_at: string | null; needs_attention: boolean }
interface Current { session: Session | null; start_request: StartResult | null }
interface Connector { id: string; charge_point_code: string; connector_number: number; status: string }
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
const messages: Record<string, string> = {
  Pending: 'Đang gửi yêu cầu đến trụ. Vui lòng chờ.',
  Accepted: 'Trụ đã chấp nhận. Đang chờ trụ xác nhận bắt đầu sạc.',
  Rejected: 'Trụ từ chối bắt đầu sạc. Hãy kiểm tra súng sạc đã cắm chắc vào xe rồi thử lại.',
  StartNotConfirmed: 'Sau 60 giây, trụ chưa xác nhận bắt đầu sạc. Hãy kiểm tra súng sạc rồi thử lại.',
  Timeout: 'Trụ chưa trả lời yêu cầu. Hãy kiểm tra kết nối rồi thử lại.',
  Offline: 'Trụ đang ngoại tuyến. Vui lòng chọn trụ khác hoặc thử lại khi trụ kết nối.',
  Disconnected: 'Trụ mất kết nối khi gửi yêu cầu. Hãy kiểm tra trạng thái trước khi thử lại.',
  ProtocolError: 'Trụ trả lời không hợp lệ. Vui lòng liên hệ hỗ trợ.',
}
async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${base}${path}`, { credentials: 'include', signal })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) throw new Error('Không tải được dữ liệu sạc. Vui lòng thử lại.')
  return await response.json() as T
}

export function DriverCharging({ stationId, stationName, showSession = true, showConnectors = true, onFindStations, onSessionStarted }: { stationId?: string; stationName?: string; showSession?: boolean; showConnectors?: boolean; onFindStations?: () => void; onSessionStarted?: () => void }) {
  const [current, setCurrent] = useState<Current | null>(null)
  const [error, setError] = useState('')
  const [connectors, setConnectors] = useState<Connector[]>([])
  const [connectorError, setConnectorError] = useState('')
  const [connectorLoading, setConnectorLoading] = useState(false)
  const [selected, setSelected] = useState('')
  const [plugged, setPlugged] = useState(false)
  const [sending, setSending] = useState(false)
  const [command, setCommand] = useState<StartResult | null>(null)
  const [requestKey, setRequestKey] = useState<{ id: string; connector: string } | null>(null)
  const [revision, setRevision] = useState(0)
  const [clock, setClock] = useState(() => Date.now())
  const notifiedRequest = useRef<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let timer: number
    async function poll() {
      try {
        const data = await read<Current>('/api/v1/driver/charging/current', controller.signal)
        if (!controller.signal.aborted) { setCurrent(data); setError(''); setClock(Date.now()) }
      } catch { if (!controller.signal.aborted) setError('Không cập nhật được phiên sạc. Dữ liệu bên dưới có thể đã cũ; đang kết nối lại.') }
      if (!controller.signal.aborted) timer = window.setTimeout(() => { void poll() }, 1000)
    }
    timer = window.setTimeout(() => { void poll() }, 0)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setConnectors([]); setSelected(''); setPlugged(false); setConnectorError('')
      if (!stationId) return
      setConnectorLoading(true)
      read<{ items: Connector[] }>(`/api/v1/driver/stations/${stationId}/connectors`, controller.signal)
        .then(data => { if (!controller.signal.aborted) { setConnectors(data.items); setConnectorLoading(false) } })
        .catch(() => { if (!controller.signal.aborted) { setConnectorError('Không tải được đầu nối.'); setConnectorLoading(false) } })
    }, 0)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [stationId, revision])
  const request = current?.start_request && (!command || current.start_request.id === command.id) ? current.start_request : command
  const pending = sending || request?.status === 'Pending' || (request?.status === 'Accepted' && (!request.deadline || Date.parse(request.deadline) > clock))
  const status = request?.status === 'Accepted' && request.deadline && Date.parse(request.deadline) <= clock ? 'StartNotConfirmed' : request?.status
  useEffect(() => {
    const confirmed = current?.start_request
    if (command && current?.session && confirmed?.id === command.id && confirmed.status === 'Started' && confirmed.session_id === current.session.id && notifiedRequest.current !== command.id) {
      notifiedRequest.current = command.id
      onSessionStarted?.()
    }
  }, [command, current, onSessionStarted])
  async function start() {
    if (!selected || !plugged || pending || current?.session || error || !connectors.some(connector => connector.id === selected && ['Available', 'Preparing'].includes(connector.status))) return
    const key = requestKey?.connector === selected ? requestKey : { id: crypto.randomUUID(), connector: selected }
    setRequestKey(key); setSending(true); setConnectorError('')
    try {
      const response = await fetch(`${base}/api/v1/driver/charging/start`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: key.id, connector_id: selected }) })
      if (response.status === 401) notifySessionUnauthorized()
      if (!response.ok) { const body = await response.json() as { detail?: string }; throw new Error(body.detail ?? 'Không gửi được yêu cầu.') }
      const result = await response.json() as StartResult
      setCommand(result); setCurrent(previous => previous ? { ...previous, start_request: result } : { session: null, start_request: result }); setRequestKey(null)
    } catch (cause) { setConnectorError(cause instanceof Error ? cause.message : 'Không gửi được yêu cầu. Hãy thử lại cùng yêu cầu để tránh gửi trùng.') }
    finally { setSending(false) }
  }
  const live = current?.session
  const selectedConnector = connectors.find(connector => connector.id === selected)
  const connectorGroups = new Map<string, Connector[]>()
  for (const connector of connectors) connectorGroups.set(connector.charge_point_code, [...(connectorGroups.get(connector.charge_point_code) ?? []), connector])
  const statusLabels: Record<string, string> = { Available: 'Sẵn sàng', Preparing: 'Đang chuẩn bị', Charging: 'Đang sạc', Reserved: 'Đã đặt chỗ', Faulted: 'Có lỗi', Unavailable: 'Không khả dụng', Finishing: 'Đang kết thúc', SuspendedEV: 'Xe tạm dừng', SuspendedEVSE: 'Trụ tạm dừng' }
  const startStatus = !live && status && messages[status] ? <p role="status" className="driver-start-status">{messages[status]}{status === 'Accepted' && request?.deadline && ` Còn khoảng ${Math.min(60, Math.max(0, Math.ceil((Date.parse(request.deadline) - clock) / 1000)))} giây.`}</p> : null
  const findStations = <a className="driver-primary-link" href="#driver-stations" onClick={event => { if (onFindStations) { event.preventDefault(); onFindStations() } }}>Tìm trạm để bắt đầu sạc</a>
  return <>
    <div className="driver-session-layout" hidden={!showSession}>
    <section className="driver-charging" aria-label="Phiên hiện tại">
      {error && <p role="alert">{error}</p>}
      {!current && !error && <p role="status">Đang kiểm tra phiên sạc…</p>}
      {live ? <>
        <div className="driver-session-location"><ChargerDrawing /><div><span className="driver-session-badge"><Icon name="charger" />Phiên đang mở</span><h2>{live.station_name}</h2><p>{live.charge_point_code} · <span className="driver-session-connector"><ConnectorSymbol status="Charging" />Đầu nối {live.connector_number}</span></p></div></div>
        <dl className="driver-session-values"><div><dt>Điện năng đã sạc</dt><dd>{live.latest_meter_at ? Number(live.energy_kwh).toLocaleString('vi-VN', { maximumFractionDigits: 3 }) : '—'} <span>kWh</span></dd></div><div><dt>Thời gian sạc</dt><dd>{Math.floor(live.elapsed_seconds / 3600)} <span>giờ</span> {Math.floor(live.elapsed_seconds % 3600 / 60)} <span>phút</span></dd></div></dl>
        <dl className="driver-session-facts"><div><dt>Bắt đầu lúc</dt><dd>{new Date(live.started_at).toLocaleString('vi-VN')}</dd></div><div><dt>Số đo gần nhất</dt><dd>{live.latest_meter_at ? new Date(live.latest_meter_at).toLocaleString('vi-VN') : 'Đang chờ số đo đầu tiên từ trụ.'}</dd></div><div><dt>Mã phiên</dt><dd>#{live.id}</dd></div><div><dt>Thời gian chi tiết</dt><dd>{Math.floor(live.elapsed_seconds / 60)} phút {live.elapsed_seconds % 60} giây</dd></div></dl>
        {live.latest_meter_at && <p className="driver-reading-age">{clock - Date.parse(live.latest_meter_at) > 30000 ? 'Số đo đã hơn 30 giây chưa cập nhật. Kiểm tra kết nối tại trạm.' : 'Số liệu cập nhật từ trụ, không cần tải lại trang.'}</p>}
        {live.needs_attention && <p role="alert">Phiên sạc cần kiểm tra. Nếu trụ ngừng sạc hoặc mất kết nối, hãy liên hệ vận hành viên.</p>}
      </> : current && <div className="driver-empty"><ChargerDrawing /><h2>Bạn chưa có phiên sạc đang diễn ra.</h2><p>Chọn trạm đang hoạt động và đối chiếu đầu nối tại trụ để bắt đầu.</p>{findStations}</div>}
      {startStatus}
    </section>
    <aside className="driver-session-guide"><h2>Trong lúc chờ xe sạc</h2><p>Bạn có thể rời màn hình rồi quay lại. Phiên được tra theo tài khoản đang đăng nhập.</p><div><Icon name="bolt" /><section><h3>Số liệu mới từ trụ</h3><p>Điện năng cập nhật khi backend nhận số đo.</p></section></div><div><Icon name="charger" /><section><h3>Đúng trụ, đúng đầu nối</h3><p>Đối chiếu mã trụ và số đầu nối với thiết bị tại trạm.</p></section></div><div><Icon name="session" /><section><h3>Khi dữ liệu bị gián đoạn</h3><p>Kiểm tra thời điểm số đo gần nhất. Mất kết nối không có nghĩa phiên đã kết thúc.</p></section></div></aside>
    </div>
    {stationId && <section className="driver-connectors" hidden={!showConnectors} aria-labelledby="driver-connectors-title"><h2 id="driver-connectors-title">Sạc tại {stationName ?? 'trạm đã chọn'}</h2>
      <p>Chọn đúng đầu nối tại trụ, cắm súng sạc vào xe rồi gửi yêu cầu.</p>
      {!showSession && error && <p role="alert">{error}</p>}
      {!showSession && startStatus}
      {live && <p role="status">Bạn đang có phiên sạc mở. <a href="#driver-session">Xem phiên hiện tại</a> trước khi bắt đầu phiên mới.</p>}
      {connectorLoading && <p role="status">Đang tải đầu nối…</p>}
      {connectorError && <p role="alert">{connectorError}</p>}
      {!connectorLoading && !connectors.length && <button className="secondary-button" onClick={() => setRevision(value => value + 1)}>Tải lại đầu nối</button>}
      {!!connectors.length && <><div className="driver-connector-picker"><label htmlFor="driver-connector">Trụ và đầu nối</label><select id="driver-connector" value={selected} disabled={pending || !!live} onChange={event => { setSelected(event.target.value); setPlugged(false); setRequestKey(null) }}><option value="">Chọn đầu nối</option>{connectors.map(connector => <option key={connector.id} value={connector.id} disabled={!['Available', 'Preparing'].includes(connector.status)}>{connector.charge_point_code} · Đầu nối {connector.connector_number} · {['Available', 'Preparing'].includes(connector.status) ? 'Sẵn sàng' : 'Chưa sẵn sàng'}</option>)}</select></div>
        <div className="driver-connector-groups">{[...connectorGroups].map(([code, items], index) => <details key={code} open={index === 0 || items.some(connector => connector.id === selected)}><summary><strong>{code}</strong><span>{items.filter(connector => ['Available', 'Preparing'].includes(connector.status)).length}/{items.length} đầu nối sẵn sàng</span></summary><div className="driver-connector-grid">{items.map(connector => <button key={connector.id} type="button" className={`driver-connector-tile ${connector.status.toLowerCase()}`} disabled={pending || !!live || !['Available', 'Preparing'].includes(connector.status)} aria-label={`${code} · Đầu nối ${connector.connector_number} · ${statusLabels[connector.status] ?? 'Chưa rõ'}`} aria-pressed={selected === connector.id} onClick={() => { setSelected(connector.id); setPlugged(false); setRequestKey(null) }}><span>{connector.connector_number}</span><ConnectorSymbol status={connector.status} /><small>{statusLabels[connector.status] ?? 'Chưa rõ'}</small></button>)}</div></details>)}</div>
        {selectedConnector && <p className="driver-selected-connector">Đã chọn: <strong>{selectedConnector.charge_point_code}</strong> · Đầu nối {selectedConnector.connector_number} · {['Available', 'Preparing'].includes(selectedConnector.status) ? 'Sẵn sàng' : 'Chưa sẵn sàng'}</p>}
        <div className="driver-start-footer"><label className="driver-plug-confirm"><input type="checkbox" checked={plugged} disabled={pending || !!live} onChange={event => setPlugged(event.target.checked)} /> Tôi đã cắm súng sạc vào xe tại đầu nối đã chọn</label><button className="primary-button" disabled={!selected || !plugged || pending || !!live || !!error || !current || !selectedConnector || !['Available', 'Preparing'].includes(selectedConnector.status)} onClick={() => { void start() }}>{sending ? 'Đang gửi yêu cầu…' : pending ? 'Đang chờ trụ bắt đầu sạc…' : 'Bắt đầu sạc'}</button><button className="secondary-button" disabled={pending || !!live} onClick={() => setRevision(value => value + 1)}>Tải lại trạng thái đầu nối</button></div>
      </>}
    </section>}
  </>
}
