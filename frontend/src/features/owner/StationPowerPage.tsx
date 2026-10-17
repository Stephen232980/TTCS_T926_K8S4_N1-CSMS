import { useEffect, useRef, useState } from 'react'
import { ownerRequest, OwnerApiError } from './ownerApi'
import './StationPower.css'

interface PowerConnector {
  connector_id: string
  charge_point_code: string
  connector_number: number
  rated_kw: string | null
  confirmed_w: number
  reserved_w: number
  desired_w: number
  baseline_verified: boolean
  status: string | null
}
interface PowerSnapshot {
  station_id: string
  version: number
  generation: number
  limit_kw: string | null
  applied_limit_w: number | null
  total_rated_w: number
  over_registered: boolean
  enabled: boolean
  state: string
  issue: string | null
  zero_limit_verified: boolean
  offline_retention_verified: boolean
  verification_note: string
  connectors: PowerConnector[]
}
const states: Record<string, string> = {
  disabled: 'Chưa bật chia tải', bootstrap: 'Đang xác minh trụ', ready: 'Đang chia tải',
  applying: 'Đang cập nhật giới hạn', degraded: 'Cần kiểm tra trụ', disable_pending: 'Đang tắt chia tải',
}
const issues: Record<string, string> = {
  power_unauthorized_session: 'Có phiên chưa được phép sạc. Phiên mới đang bị chặn; hệ thống đang yêu cầu dừng phiên đó.',
  power_configuration_incomplete: 'Đầu nối đã thay đổi. Hãy cập nhật lại cấu hình công suất.',
  power_capability_unverified: 'Trụ chưa xác nhận khả năng điều khiển công suất bằng W hoặc đang mất liên lạc.',
  power_baseline_failed: 'Chưa xác minh được giới hạn mặc định. Phiên mới đang bị chặn.',
  power_profile_not_verified: 'Trụ chưa xác nhận mức công suất mới. Ngân sách đã cấp vẫn được giữ.',
  offline_budget_retained: 'Có trụ mất liên lạc. Phần công suất đã cấp vẫn được giữ, phiên mới đang bị chặn.',
  offline_budget_exceeds_requested_limit: 'Công suất của trụ mất liên lạc còn vượt hạn mức yêu cầu. Chưa áp dụng hạn mức mới.',
  power_commissioning_required: 'Cần ghi nhận kết quả kiểm tra thiết bị trước khi bật chia tải.',
  power_control_requires_no_open_sessions: 'Hãy kết thúc các phiên đang mở trước khi bật hoặc tắt chia tải.',
  power_plan_in_progress: 'Trụ đang nhận kế hoạch. Hãy chờ hoàn tất rồi thao tác lại.',
  power_version_conflict: 'Cấu hình đã được thay đổi. Hãy tải lại trước khi lưu.',
  power_disable_failed: 'Chưa gỡ được hết hồ sơ công suất. Chia tải vẫn được bảo vệ, hãy kiểm tra trụ.',
  power_disable_waiting_for_device: 'Chưa thể tắt vì trụ mất liên lạc hoặc còn phiên mở.',
}
function errorText(error: unknown) {
  if (error instanceof OwnerApiError && typeof error.detail === 'string') return issues[error.detail] ?? error.message
  return error instanceof Error ? error.message : 'Không thực hiện được. Hãy thử lại.'
}
function kw(watts: number | null) {
  return watts === null ? 'Chưa áp dụng' : `${(watts / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 3 })} kW`
}

export function StationPowerPage() {
  const [stations, setStations] = useState<{ id: string; name: string }[]>([])
  const [stationId, setStationId] = useState('')
  const [snapshot, setSnapshot] = useState<PowerSnapshot | null>(null)
  const [limit, setLimit] = useState('')
  const [formVersion, setFormVersion] = useState(0)
  const [ratings, setRatings] = useState<Record<string, string>>({})
  const [zeroVerified, setZeroVerified] = useState(false)
  const [offlineVerified, setOfflineVerified] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)
  const [listRetry, setListRetry] = useState(0)
  const requestSequence = useRef(0)
  const mutationActive = useRef(false)
  useEffect(() => {
    const controller = new AbortController()
    void ownerRequest<{ items: { id: string; name: string }[]; total_pages: number }>('/owner/stations?page_size=100', { signal: controller.signal })
      .then(async first => {
        const items = [...first.items]
        for (let page = 2; page <= first.total_pages; page++) {
          const next = await ownerRequest<{ items: { id: string; name: string }[] }>(`/owner/stations?page_size=100&page=${page}`, { signal: controller.signal })
          items.push(...next.items)
        }
        if (!controller.signal.aborted) {
          setStations(items)
          setStationId(previous => items.some(item => item.id === previous) ? previous : items[0]?.id ?? '')
        }
      }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)) })
    return () => controller.abort()
  }, [listRetry])
  useEffect(() => {
    if (!stationId) return
    const controller = new AbortController()
    let firstLoad = true
    const load = async () => {
      if (mutationActive.current) return
      const sequence = ++requestSequence.current
      try {
        const data = await ownerRequest<PowerSnapshot>(`/owner/stations/${stationId}/power-config`, { signal: controller.signal })
        if (controller.signal.aborted || sequence !== requestSequence.current || mutationActive.current) return
        setSnapshot(data)
        if (firstLoad) {
          setFormVersion(data.version)
          setLimit(data.limit_kw ?? '')
          setRatings(Object.fromEntries(data.connectors.map(c => [c.connector_id, c.rated_kw ?? ''])))
          setZeroVerified(data.zero_limit_verified); setOfflineVerified(data.offline_retention_verified); setNote(data.verification_note)
          firstLoad = false
          setError('')
        }
      } catch (cause) { if (!controller.signal.aborted && sequence === requestSequence.current && !mutationActive.current) setError(errorText(cause)) }
    }
    void load()
    const timer = window.setInterval(() => { if (!document.hidden) void load() }, 5000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [stationId, retry])
  async function act(action: 'save' | 'enable' | 'disable') {
    if (!snapshot || snapshot.station_id !== stationId || mutationActive.current) return
    mutationActive.current = true
    ++requestSequence.current
    setBusy(true); setError(''); setNotice('')
    try {
      const path = `/owner/stations/${stationId}/${action === 'save' ? 'power-config' : `power-control/${action}`}`
      const body = action === 'save' ? {
        version: formVersion, limit_kw: limit,
        connectors: snapshot.connectors.map(c => ({ connector_id: c.connector_id, rated_kw: ratings[c.connector_id] ?? '' })),
        zero_limit_verified: zeroVerified, offline_retention_verified: offlineVerified, verification_note: note,
      } : { version: snapshot.version }
      const data = await ownerRequest<PowerSnapshot>(path, { method: action === 'save' ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      setSnapshot(data)
      setFormVersion(data.version)
      setNotice(action === 'save' ? 'Đã lưu cấu hình. Hạn mức mới chỉ có hiệu lực khi trụ xác nhận.' : 'Đã nhận yêu cầu. Theo dõi trạng thái trụ để biết khi nào hoàn tất.')
    } catch (cause) { setError(errorText(cause)) } finally { mutationActive.current = false; setBusy(false) }
  }
  const transition = snapshot && ['bootstrap', 'applying', 'disable_pending'].includes(snapshot.state)
  return <section className="owner-page owner-power-page">
    <header className="owner-heading"><div><h1>Công suất</h1><p>Đặt hạn mức tải sạc và theo dõi mức đã được trụ xác nhận.</p></div></header>
    <div className="owner-panel owner-power-scroll">
      <label htmlFor="power-station">Trạm sạc<select id="power-station" value={stationId} disabled={busy} onChange={event => { setStationId(event.target.value); setSnapshot(null); setError(''); setNotice('') }}>
        {stations.map(station => <option key={station.id} value={station.id}>{station.name}</option>)}
      </select></label>
      {!stations.length && !error && <p role="status">Chưa có trạm. Tạo trạm và đầu nối trước khi khai báo công suất.</p>}
      {stationId && !snapshot && !error && <p role="status">Đang tải công suất…</p>}
      {error && <p className="owner-error" role="alert">{error} <button type="button" disabled={busy} onClick={() => { setSnapshot(null); setError(''); setNotice(''); if (!stations.length) setListRetry(value => value + 1); else setRetry(value => value + 1) }}>Tải lại</button></p>}
      {notice && <p className="owner-subtle" role="status">{notice}</p>}
      {snapshot && snapshot.station_id === stationId && <>
        <div className="owner-power-summary"><strong>{states[snapshot.state] ?? snapshot.state}</strong><span>Kế hoạch #{snapshot.generation}</span><span>Hạn mức đã lưu: {snapshot.limit_kw === null ? 'Chưa khai báo' : kw(Number(snapshot.limit_kw) * 1000)}</span><span>Hạn mức đã áp dụng: {kw(snapshot.enabled ? snapshot.applied_limit_w : null)}</span><span>Tổng danh định: {kw(snapshot.total_rated_w)}</span></div>
        {snapshot.issue && <p className="owner-error" role="status">{issues[snapshot.issue] ?? 'Trụ chưa xác nhận kế hoạch. Hãy kiểm tra kết nối và cấu hình.'}</p>}
        {snapshot.over_registered && <p className="owner-subtle">Tổng danh định vượt hạn mức. Điều này được phép; chia tải sẽ giới hạn phần cấp cho các xe.</p>}
        <form onSubmit={event => { event.preventDefault(); void act('save') }}>
          <label htmlFor="station-limit">Hạn mức tải sạc (kW)<input id="station-limit" inputMode="decimal" type="number" min="0.001" max="999999.999" step="0.001" value={limit} onChange={event => setLimit(event.target.value)} required disabled={busy || !!transition} /></label>
          <p className="owner-subtle">Giá trị nhập chỉ được cập nhật sau khi lưu. Hạn mức này chỉ dành cho tải sạc, chưa bao gồm thiết bị khác trong tòa nhà.</p>
          <div className="owner-power-table-wrap"><table><caption>Danh định và phân bổ từng đầu nối</caption><thead><tr><th>Trụ / đầu nối</th><th>Danh định (kW)</th><th>Yêu cầu đã lưu</th><th>Đã xác nhận</th><th>Ngân sách giữ</th></tr></thead><tbody>
            {snapshot.connectors.map(connector => <tr key={connector.connector_id}><td>{connector.charge_point_code} / {connector.connector_number}<span className="owner-subtle">{connector.baseline_verified ? 'Đã xác minh hồ sơ mặc định' : 'Chưa xác minh hồ sơ mặc định'}</span></td><td><input aria-label={`Danh định ${connector.charge_point_code} đầu nối ${connector.connector_number}`} type="number" min="0.001" max="99999.999" step="0.001" required value={ratings[connector.connector_id] ?? ''} onChange={event => setRatings(previous => ({ ...previous, [connector.connector_id]: event.target.value }))} disabled={busy || !!transition} /></td><td>{kw(connector.desired_w)}</td><td>{kw(connector.confirmed_w)}</td><td>{kw(connector.reserved_w)}</td></tr>)}
          </tbody></table></div>
          <fieldset disabled={busy || !!transition}><legend>Kiểm tra thiết bị trước khi bật</legend>
            <label className="owner-power-check"><input type="checkbox" checked={zeroVerified} onChange={event => setZeroVerified(event.target.checked)} />Đã thử giới hạn 0 W: trụ không cấp điện và cho phép cấp lại theo phiên.</label>
            <label className="owner-power-check"><input type="checkbox" checked={offlineVerified} onChange={event => setOfflineVerified(event.target.checked)} />Đã thử mất mạng và khởi động lại: trụ giữ giới hạn, không tự sạc ngoài kế hoạch.</label>
            <label htmlFor="power-evidence">Ghi nhận thiết bị, firmware và kết quả thử<input id="power-evidence" value={note} maxLength={500} onChange={event => setNote(event.target.value)} /></label>
          </fieldset>
          <div className="owner-power-actions"><button className="primary-button" type="submit" disabled={busy || !!transition || !snapshot.connectors.length}>{busy ? 'Đang xử lý…' : 'Lưu cấu hình'}</button>
            <button className="secondary-button" type="button" disabled={busy || !!transition || snapshot.version === 0 || !snapshot.zero_limit_verified || !snapshot.offline_retention_verified || !snapshot.verification_note || (snapshot.enabled && snapshot.state === 'ready')} onClick={() => void act('enable')}>{snapshot.enabled ? 'Kiểm tra lại chia tải' : 'Bật chia tải'}</button>
            {snapshot.enabled && <button className="secondary-button" type="button" disabled={busy || !!transition} onClick={() => void act('disable')}>Tắt chia tải</button>}
          </div>
        </form>
        <p className="owner-subtle">Bật/tắt khi không còn phiên mở. Khai báo hạn mức chưa chứng minh thiết bị đã áp dụng; trạng thái và kết quả thử mới là căn cứ.</p>
      </>}
    </div>
  </section>
}
