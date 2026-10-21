import { useEffect, useRef, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'
import { ChargerDrawing, ConnectorSymbol } from '../owner/OwnerVisuals'
import { DriverSessionControls } from './DriverSessionControls'
import { Icon } from '../../components/icons/Icon'
import { ReservationForm } from '../reservations/ReservationForm'
import { DriverStartSummary, type DriverStartPricing } from './DriverStartSummary'
interface StartResult { id: string; status: string; deadline: string | null; session_id?: number | null; connector_id?: string; rejection_reason?: string | null; balance_vnd?: number | null; minimum_balance_vnd?: number | null }
interface Session { id: number; station_name: string; charge_point_code: string; connector_number: number; started_at: string; ended_at?: string | null; demo_unplug_available?: boolean; energy_kwh: string | number; elapsed_seconds: number; latest_meter_at: string | null; needs_attention: boolean }
interface Current { awaiting_unplug?: Session | null; session: Session | null; start_request: StartResult | null }
interface Connector { id: string; charge_point_code: string; connector_number: number; status: string; available?: boolean; can_start?: boolean; own_reservation?: boolean; reservation_capability?: string }
const canStart = (connector: Connector) => connector.can_start ?? (['Available', 'Preparing'].includes(connector.status) || (connector.status === 'Reserved' && connector.own_reservation === true))
const chargingLabel = (connector: Connector) => connector.own_reservation ? (canStart(connector) ? 'Đã đặt chỗ của bạn · Có thể bắt đầu sạc' : 'Đặt chỗ của bạn · Chờ xác nhận') : canStart(connector) ? 'Sẵn sàng' : 'Chưa sẵn sàng'
type WalletEligibilityReason = 'wallet_low' | 'wallet_missing' | 'wallet_locked' | 'tariff_unavailable'
interface WalletFailure { reason: WalletEligibilityReason; balance_vnd: number | null; minimum_balance_vnd: number | null }
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
const walletEligibilityMessages: Record<WalletEligibilityReason, string> = {
  wallet_low: 'Số dư ví hiện tại chưa đạt mức tối thiểu để bắt đầu sạc tại trạm này. Vui lòng nạp thêm tiền rồi thử lại.',
  wallet_missing: 'Chưa tìm thấy ví của bạn. Vui lòng kiểm tra thông tin ví trước khi bắt đầu sạc.',
  wallet_locked: 'Ví của bạn hiện đang bị khóa nên chưa thể bắt đầu sạc. Vui lòng liên hệ hỗ trợ.',
  tariff_unavailable: 'Chưa có thông tin giá sạc hợp lệ tại trạm này. Vui lòng thử lại sau hoặc chọn trạm khác.',
}
function walletEligibilityReason(detail: unknown): WalletEligibilityReason | null {
  const reason = typeof detail === 'string'
    ? detail
    : detail && typeof detail === 'object' && 'reason' in detail
      ? detail.reason
      : null
  return typeof reason === 'string' && Object.hasOwn(walletEligibilityMessages, reason)
    ? reason as WalletEligibilityReason
    : null
}
function walletEligibilityFailure(detail: unknown): WalletFailure | null {
  const reason = walletEligibilityReason(detail)
  if (!reason) return null
  const value = detail && typeof detail === 'object' ? detail as Record<string, unknown> : {}
  const amount = (field: string) => typeof value[field] === 'number' && Number.isSafeInteger(value[field]) ? value[field] as number : null
  return { reason, balance_vnd: amount('balance_vnd'), minimum_balance_vnd: amount('minimum_balance_vnd') }
}
async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${base}${path}`, { credentials: 'include', signal })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) throw new Error('Không tải được dữ liệu sạc. Vui lòng thử lại.')
  return await response.json() as T
}

export function DriverCharging({ ownerId = 'session', stationId, stationName, stationPricing, showSession = true, showConnectors = true, onFindStations, onSessionStarted }: { ownerId?: string; stationId?: string; stationName?: string; stationPricing?: DriverStartPricing; showSession?: boolean; showConnectors?: boolean; onFindStations?: () => void; onSessionStarted?: () => void }) {
  const [current, setCurrent] = useState<Current | null>(null)
  const lastOccupiedSession = useRef<number | null>(null)
  const [releasedSession, setReleasedSession] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [connectors, setConnectors] = useState<Connector[]>([])
  const [connectorError, setConnectorError] = useState('')
  const [walletFailure, setWalletFailure] = useState<(WalletFailure & { stationId?: string; connectorId: string }) | null>(null)
  const [dismissedRequest, setDismissedRequest] = useState<string | null>(null)
  const [connectorLoading, setConnectorLoading] = useState(false)
  const [connectorStale, setConnectorStale] = useState(false)
  const previousStation = useRef<string | undefined>(undefined)
  const hasConnectors = useRef(false)
  const [selected, setSelected] = useState('')
  const [chargePoint, setChargePoint] = useState('')
  const [plugged, setPlugged] = useState(false)
  const [sending, setSending] = useState(false)
  const [command, setCommand] = useState<StartResult | null>(null)
  const [requestKey, setRequestKey] = useState<{ id: string; connector: string } | null>(null)
  const [revision, setRevision] = useState(0)
  const [clock, setClock] = useState(() => Date.now())
  const [receivedAt, setReceivedAt] = useState(() => Date.now())
  const notifiedRequest = useRef<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let source: EventSource | undefined
    let timer: number | undefined
    let stopped = false
    let denied = false
    let version = 0
    const stale = 'Không cập nhật được phiên sạc. Dữ liệu bên dưới có thể đã cũ; đang kết nối lại.'
    const accept = (data: Current, clearError = true) => {
      const occupied = data.session ?? data.awaiting_unplug
      if (occupied) {
        lastOccupiedSession.current = occupied.id
        setReleasedSession(null)
      } else if (lastOccupiedSession.current !== null) {
        setReleasedSession(lastOccupiedSession.current)
        lastOccupiedSession.current = null
      }
      setCurrent(data)
      setClock(Date.now())
      setReceivedAt(Date.now())
      if (clearError) setError('')
    }
    const deny = () => {
      denied = true; source?.close(); controller.abort()
      setCurrent(null); setCommand(null); setError('Bạn không còn quyền theo dõi phiên sạc. Vui lòng đăng nhập lại.')
      notifySessionUnauthorized()
    }
    async function load(keepStreamError = false) {
      const issuedVersion = version
      try {
        const response = await fetch(`${base}/api/v1/driver/charging/current`, { credentials: 'include', signal: controller.signal })
        if (stopped || denied) return
        if (response.status === 401 || response.status === 403) { deny(); return }
        if (!response.ok) throw new Error(stale)
        const data = await response.json() as Current
        if (!stopped && !denied && issuedVersion === version) accept(data, !keepStreamError)
      } catch { if (!stopped && !denied && !controller.signal.aborted && issuedVersion === version) setError(stale) }
    }
    function connect() {
      if (stopped || denied) return
      const opened = new EventSource(`${base}/api/v1/driver/charging/current/events`, { withCredentials: true })
      source = opened
      opened.onmessage = event => {
        if (stopped || denied || source !== opened) return
        try {
          const data = JSON.parse(event.data) as Current
          if (!data || typeof data !== 'object' || !('session' in data) || !('start_request' in data)) throw new Error(stale)
          version++; accept(data)
        } catch {
          setError(stale); opened.close(); source = undefined
          timer = window.setTimeout(connect, 1000)
        }
      }
      opened.onerror = () => { if (!stopped && !denied && source === opened) { setError(stale); void load(true) } }
      opened.addEventListener('access-denied', () => { if (!stopped && !denied && source === opened) deny() })
    }
    async function poll() {
      await load()
      if (!stopped && !denied) timer = window.setTimeout(() => { void poll() }, 1000)
    }
    timer = window.setTimeout(() => {
      if (typeof EventSource !== 'undefined') { void load(); connect() }
      else void poll()
    }, 0)
    const clockTimer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => { stopped = true; controller.abort(); source?.close(); window.clearTimeout(timer); window.clearInterval(clockTimer) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    let running = false
    async function load() {
      if (!stationId || running || document.hidden) return
      running = true
      setConnectorLoading(!hasConnectors.current)
      try {
        const data = await read<{ items: Connector[] }>(`/api/v1/driver/stations/${stationId}/connectors`, controller.signal)
        if (!controller.signal.aborted) {
          setConnectors(data.items); setSelected(value => data.items.some(item => item.id === value) ? value : '')
          hasConnectors.current = data.items.length > 0; setConnectorStale(false); setConnectorLoading(false)
          setConnectorError(value => value.startsWith('Không tải được đầu nối') ? '' : value)
        }
      } catch { if (!controller.signal.aborted) { setConnectorError('Không tải được đầu nối. Đang tự thử lại; chưa thể gửi yêu cầu.'); setConnectorStale(true); setConnectorLoading(false) } }
      finally { running = false }
    }
    const timer = window.setTimeout(() => {
      if (previousStation.current !== stationId) {
        previousStation.current = stationId; hasConnectors.current = false
        setConnectors([]); setSelected(''); setChargePoint(''); setPlugged(false); setConnectorError(''); setWalletFailure(null)
      }
      void load()
    }, 0)
    const poll = window.setInterval(() => { if (showConnectors) void load() }, 5000)
    const visible = () => { if (showConnectors && !document.hidden) void load() }
    document.addEventListener('visibilitychange', visible)
    return () => { controller.abort(); window.clearTimeout(timer); window.clearInterval(poll); document.removeEventListener('visibilitychange', visible) }
  }, [stationId, revision, showConnectors])
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
    if (!selected || !plugged || pending || current?.session || error || connectorStale || !connectors.some(connector => connector.id === selected && canStart(connector))) return
    const key = requestKey?.connector === selected ? requestKey : { id: crypto.randomUUID(), connector: selected }
    setRequestKey(key); setSending(true); setConnectorError(''); setWalletFailure(null)
    try {
      const response = await fetch(`${base}/api/v1/driver/charging/start`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: key.id, connector_id: selected }) })
      if (response.status === 401) notifySessionUnauthorized()
      if (!response.ok) {
        const body = await response.json() as { detail?: unknown }
        const failure = walletEligibilityFailure(body.detail)
        if (failure) { setWalletFailure({ ...failure, stationId, connectorId: selected }); setRequestKey(null); return }
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Không gửi được yêu cầu.')
      }
      const result = await response.json() as StartResult
      setCommand(result); setCurrent(previous => previous ? { ...previous, start_request: result } : { session: null, start_request: result }); setRequestKey(null)
    } catch (cause) { setConnectorError(cause instanceof Error ? cause.message : 'Không gửi được yêu cầu. Hãy thử lại cùng yêu cầu để tránh gửi trùng.') }
    finally { setSending(false) }
  }
  const live = current?.session
  const elapsedSeconds = live ? live.elapsed_seconds + Math.max(0, Math.floor((clock - receivedAt) / 1000)) : 0
  const selectedConnector = connectors.find(connector => connector.id === selected)
  const connectorGroups = new Map<string, Connector[]>()
  for (const connector of connectors) connectorGroups.set(connector.charge_point_code, [...(connectorGroups.get(connector.charge_point_code) ?? []), connector])
  const visibleChargePoint = selectedConnector?.charge_point_code ?? (connectorGroups.has(chargePoint) ? chargePoint : connectors[0]?.charge_point_code)
  const visibleConnectors = visibleChargePoint ? connectorGroups.get(visibleChargePoint) ?? [] : []
  const statusLabels: Record<string, string> = { Available: 'Sẵn sàng', Preparing: 'Đang chuẩn bị', Charging: 'Đang sạc', Reserved: 'Đã đặt chỗ', Faulted: 'Có lỗi', Unavailable: 'Không khả dụng', Finishing: 'Đang kết thúc', SuspendedEV: 'Xe tạm dừng', SuspendedEVSE: 'Trụ tạm dừng' }
  const failure = walletFailure && walletFailure.stationId === stationId && walletFailure.connectorId === selected ? walletFailure
    : status === 'Rejected' && request?.connector_id === selected && request.id !== dismissedRequest
      ? walletEligibilityFailure({ reason: request.rejection_reason, balance_vnd: request.balance_vnd, minimum_balance_vnd: request.minimum_balance_vnd }) : null
  const startMessage = request?.rejection_reason === 'station_unavailable' ? 'Trạm đã tạm ngừng hoặc không còn khả dụng. Chọn trạm khác để bắt đầu sạc.' : request?.rejection_reason === 'reservation_unavailable' ? 'Trụ chưa xác nhận đúng quyền giữ chỗ. Kiểm tra đặt chỗ của bạn trước khi sạc.' : status ? messages[status] : ''
  const startStatus = !live && !failure && status && startMessage ? <p role="status" className="driver-start-status">{startMessage}{status === 'Accepted' && request?.deadline && ` Còn khoảng ${Math.min(60, Math.max(0, Math.ceil((Date.parse(request.deadline) - clock) / 1000)))} giây.`}</p> : null
  const walletFailureMessage = failure ? walletEligibilityMessages[failure.reason] : null
  function chooseConnector(id: string) {
    const connector = connectors.find(item => item.id === id)
    if (connector) setChargePoint(connector.charge_point_code)
    setSelected(id); setPlugged(false); setRequestKey(null); setWalletFailure(null); setDismissedRequest(request?.id ?? null)
  }
  const findStations = <a className="driver-primary-link" href="#driver-stations" onClick={event => { if (onFindStations) { event.preventDefault(); onFindStations() } }}>Tìm trạm để bắt đầu sạc</a>
  return <>
    <div className="driver-session-layout" hidden={!showSession}>
    <section className="driver-charging" aria-label="Phiên hiện tại">
      {error && <p role="alert">{error}</p>}
      {!current && !error && <p role="status">Đang kiểm tra phiên sạc…</p>}
      {live ? <>
        <div className="driver-session-location"><ChargerDrawing /><div><span className="driver-session-badge"><Icon name="charger" />Phiên đang mở</span><h2>{live.station_name}</h2><p>{live.charge_point_code} · <span className="driver-session-connector"><ConnectorSymbol status="Charging" />Đầu nối {live.connector_number}</span></p></div></div>
        <dl className="driver-session-values"><div><dt>Điện năng đã sạc</dt><dd>{live.latest_meter_at ? Number(live.energy_kwh).toLocaleString('vi-VN', { maximumFractionDigits: 3 }) : '—'} <span>kWh</span></dd></div><div><dt>Thời gian sạc</dt><dd>{Math.floor(elapsedSeconds / 3600)} <span>giờ</span> {Math.floor(elapsedSeconds % 3600 / 60)} <span>phút</span></dd></div></dl>
        <dl className="driver-session-facts"><div><dt>Bắt đầu lúc</dt><dd>{new Date(live.started_at).toLocaleString('vi-VN')}</dd></div><div><dt>Số đo gần nhất</dt><dd>{live.latest_meter_at ? new Date(live.latest_meter_at).toLocaleString('vi-VN') : 'Đang chờ số đo đầu tiên từ trụ.'}</dd></div><div><dt>Mã phiên</dt><dd>#{live.id}</dd></div><div><dt>Thời gian chi tiết</dt><dd>{Math.floor(elapsedSeconds / 60)} phút {elapsedSeconds % 60} giây</dd></div></dl>
        {live.latest_meter_at && <p className="driver-reading-age">{clock - Date.parse(live.latest_meter_at) > 30000 ? 'Số đo đã hơn 30 giây chưa cập nhật. Kiểm tra kết nối tại trạm.' : 'Số liệu cập nhật từ trụ, không cần tải lại trang.'}</p>}
        {live.needs_attention && <p role="alert">Phiên sạc cần kiểm tra. Nếu trụ ngừng sạc hoặc mất kết nối, hãy liên hệ vận hành viên.</p>}
      </> : current?.awaiting_unplug ? <div className="driver-awaiting-session"><h2>Phiên #{current.awaiting_unplug.id} đang chờ rút súng</h2><p>{current.awaiting_unplug.station_name} · {current.awaiting_unplug.charge_point_code} · Đầu nối {current.awaiting_unplug.connector_number}</p></div> : current && <div className="driver-empty"><ChargerDrawing /><h2>Bạn chưa có phiên sạc đang diễn ra.</h2><p>Chọn trạm đang hoạt động và đối chiếu đầu nối tại trụ để bắt đầu.</p>{findStations}</div>}
      {(live || current?.awaiting_unplug) && <DriverSessionControls key={(live ?? current!.awaiting_unplug)!.id} session={(live ?? current!.awaiting_unplug)!} onRefresh={() => setRevision(value => value + 1)} />}
      {releasedSession !== null && <p className="driver-release-confirmed" role="status">Trụ đã xác nhận giải phóng đầu nối. <a href={`#driver-invoice-${releasedSession}`}>Xem trạng thái hóa đơn phiên #{releasedSession}</a></p>}
      {startStatus}
    </section>
    <aside className="driver-session-guide"><h2>Trong lúc chờ xe sạc</h2><p>Bạn có thể rời màn hình rồi quay lại. Phiên được tra theo tài khoản đang đăng nhập.</p><div><Icon name="bolt" /><section><h3>Số liệu mới từ trụ</h3><p>Điện năng cập nhật khi backend nhận số đo.</p></section></div><div><Icon name="charger" /><section><h3>Đúng trụ, đúng đầu nối</h3><p>Đối chiếu mã trụ và số đầu nối với thiết bị tại trạm.</p></section></div><div><Icon name="session" /><section><h3>Khi dữ liệu bị gián đoạn</h3><p>Kiểm tra thời điểm số đo gần nhất. Mất kết nối không có nghĩa phiên đã kết thúc.</p></section></div></aside>
    </div>
    {stationId && <section className="driver-connectors" hidden={!showConnectors} aria-labelledby="driver-connectors-title"><h2 id="driver-connectors-title">Sạc tại {stationName ?? 'trạm đã chọn'}</h2>
      {showSession && <p>Chọn đúng đầu nối tại trụ, cắm súng sạc vào xe rồi gửi yêu cầu.</p>}
      {!showSession && error && <p role="alert">{error}</p>}
      {!showSession && startStatus}
      {live && <p role="status">Bạn đang có phiên sạc mở. <a href="#driver-session">Xem phiên hiện tại</a> trước khi bắt đầu phiên mới.</p>}
      {connectorLoading && <p role="status">Đang tải đầu nối…</p>}
      {connectorError && <p role="alert">{connectorError}</p>}
      {walletFailureMessage && <div className="driver-start-reason" role="alert"><p>{walletFailureMessage}</p>{failure?.reason === 'wallet_low' && <><p>{failure.balance_vnd !== null && <>Số dư lúc kiểm tra: <strong>{failure.balance_vnd.toLocaleString('vi-VN')}đ</strong>. </>}{failure.minimum_balance_vnd !== null && <>Cần tối thiểu: <strong>{failure.minimum_balance_vnd.toLocaleString('vi-VN')}đ</strong>.</>}</p><a className="driver-primary-link" href="#driver-wallet">Nạp tiền</a></>}</div>}
      {!connectorLoading && !connectors.length && !connectorError && <p>Trạm chưa có đầu nối được khai báo.</p>}
      {!!connectors.length && <div className="driver-start-layout"><div className="driver-connector-selection"><div className="driver-connector-picker"><label htmlFor="driver-charge-point">Trụ sạc</label><select id="driver-charge-point" value={visibleChargePoint} disabled={pending || !!live || !!current?.awaiting_unplug} onChange={event => { setChargePoint(event.target.value); chooseConnector('') }}>{[...connectorGroups.keys()].map(code => <option key={code} value={code}>{code}</option>)}</select></div>
        <div className="driver-connector-group" role="group" aria-label={`Đầu nối tại ${visibleChargePoint}`}>
          <div className="driver-connector-group-heading"><strong>Đầu nối</strong><span>{visibleConnectors.filter(connector => canStart(connector)).length}/{visibleConnectors.length} sẵn sàng</span></div>
          <div className="driver-connector-grid">{visibleConnectors.map(connector => <button key={connector.id} type="button" className={`driver-connector-tile ${connector.status.toLowerCase()}`} disabled={pending || !!live || !!current?.awaiting_unplug || !canStart(connector)} aria-label={`${connector.charge_point_code} · Đầu nối ${connector.connector_number} · ${statusLabels[connector.status] ?? 'Chưa rõ'}`} aria-description={connector.own_reservation ? chargingLabel(connector) : undefined} aria-pressed={selected === connector.id} onClick={() => chooseConnector(connector.id)}><span>{connector.connector_number}</span><ConnectorSymbol status={connector.status} /><small>{connector.own_reservation ? 'Chỗ của bạn' : statusLabels[connector.status] ?? 'Chưa rõ'}</small></button>)}</div>
        </div>
        </div><div className="driver-start-footer">{showConnectors && <DriverStartSummary key={stationId} pricing={stationPricing} />}<label className="driver-plug-confirm"><input type="checkbox" checked={plugged} disabled={pending || !!live || !!current?.awaiting_unplug} onChange={event => setPlugged(event.target.checked)} /> Tôi đã cắm súng sạc vào xe tại đầu nối đã chọn</label><button className="primary-button" disabled={!selected || !plugged || pending || !!live || !!current?.awaiting_unplug || !!error || connectorStale || !current || !selectedConnector || !canStart(selectedConnector)} onClick={() => { void start() }}>{sending ? 'Đang gửi yêu cầu…' : pending ? 'Đang chờ trụ bắt đầu sạc…' : 'Bắt đầu sạc'}</button>{selectedConnector && selectedConnector.reservation_capability !== undefined && <ReservationForm key={selectedConnector.id} connectorId={selectedConnector.id} capability={selectedConnector.reservation_capability} ownReservation={selectedConnector.own_reservation === true} available={selectedConnector.available === true && !connectorStale && !pending && !live && !current?.awaiting_unplug} ownerId={ownerId} onChanged={() => setRevision(value => value + 1)} onSelectAlternative={id => { if (!connectors.some(item => item.id === id)) return; chooseConnector(id); setRevision(value => value + 1); window.requestAnimationFrame(() => document.getElementById('driver-charge-point')?.focus()) }} />}</div>
      </div>}
    </section>}
  </>
}
