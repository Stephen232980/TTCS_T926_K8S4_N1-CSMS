import { useEffect, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

interface StartResult { id: string; status: string; deadline: string | null }
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

export function DriverCharging({ stationId, stationName }: { stationId?: string; stationName?: string }) {
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
  async function start() {
    if (!selected || !plugged || pending || current?.session || error) return
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
  return <>
    <section className="driver-charging" aria-labelledby="driver-charging-title">
      <h2 id="driver-charging-title">Phiên sạc của bạn</h2>
      {error && <p role="alert">{error}</p>}
      {!current && !error && <p role="status">Đang kiểm tra phiên sạc…</p>}
      {live ? <>
        <p className="driver-session-location"><strong>{live.station_name}</strong> · {live.charge_point_code} · Đầu nối {live.connector_number}</p>
        <dl className="driver-session-values"><div><dt>Điện năng đã sạc</dt><dd>{Number(live.energy_kwh).toLocaleString('vi-VN', { maximumFractionDigits: 3 })} <span>kWh</span></dd></div><div><dt>Thời gian sạc</dt><dd>{Math.floor(live.elapsed_seconds / 60)} <span>phút</span> {live.elapsed_seconds % 60} <span>giây</span></dd></div></dl>
        <p>Bắt đầu lúc {new Date(live.started_at).toLocaleString('vi-VN')}. {live.latest_meter_at ? `Số liệu mới nhất: ${new Date(live.latest_meter_at).toLocaleTimeString('vi-VN')}.` : 'Đang chờ số đo đầu tiên từ trụ.'}</p>
        {live.needs_attention && <p role="alert">Phiên sạc cần kiểm tra. Nếu trụ ngừng sạc hoặc mất kết nối, hãy liên hệ vận hành viên.</p>}
      </> : current && <><p>Bạn chưa có phiên sạc đang diễn ra.</p><a href="#driver-stations">Tìm trạm để bắt đầu sạc</a></>}
      {!live && status && messages[status] && <p role="status" className="driver-start-status">{messages[status]}{status === 'Accepted' && request?.deadline && ` Còn khoảng ${Math.min(60, Math.max(0, Math.ceil((Date.parse(request.deadline) - clock) / 1000)))} giây.`}</p>}
    </section>
    {stationId && <section className="driver-connectors" aria-labelledby="driver-connectors-title"><h2 id="driver-connectors-title">Sạc tại {stationName ?? 'trạm đã chọn'}</h2>
      <p>Chọn đúng đầu nối tại trụ, cắm súng sạc vào xe rồi gửi yêu cầu.</p>
      {connectorLoading && <p role="status">Đang tải đầu nối…</p>}
      {connectorError && <p role="alert">{connectorError}</p>}
      {!connectorLoading && !connectors.length && <button className="secondary-button" onClick={() => setRevision(value => value + 1)}>Tải lại đầu nối</button>}
      {!!connectors.length && <><label htmlFor="driver-connector">Trụ và đầu nối</label><select id="driver-connector" value={selected} disabled={pending || !!live} onChange={event => { setSelected(event.target.value); setPlugged(false); setRequestKey(null) }}><option value="">Chọn đầu nối</option>{connectors.map(connector => <option key={connector.id} value={connector.id} disabled={!['Available', 'Preparing'].includes(connector.status)}>{connector.charge_point_code} · Đầu nối {connector.connector_number} · {['Available', 'Preparing'].includes(connector.status) ? 'Sẵn sàng' : 'Chưa sẵn sàng'}</option>)}</select>
        {selectedConnector && <p className="driver-selected-connector">Đã chọn: <strong>{selectedConnector.charge_point_code}</strong> · Đầu nối {selectedConnector.connector_number} · {['Available', 'Preparing'].includes(selectedConnector.status) ? 'Sẵn sàng' : 'Chưa sẵn sàng'}</p>}
        <label className="driver-plug-confirm"><input type="checkbox" checked={plugged} disabled={pending || !!live} onChange={event => setPlugged(event.target.checked)} /> Tôi đã cắm súng sạc vào xe tại đầu nối đã chọn</label>
        <button className="primary-button" disabled={!selected || !plugged || pending || !!live || !!error || !current} onClick={() => { void start() }}>{sending ? 'Đang gửi yêu cầu…' : pending ? 'Đang chờ trụ bắt đầu sạc…' : 'Bắt đầu sạc'}</button>
      </>}
    </section>}
  </>
}
