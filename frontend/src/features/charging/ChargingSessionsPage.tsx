import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { MeterChart } from './MeterChart'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

interface Session {
  id: number; station_name: string; charge_point_code: string; connector_number: number
  tag_tail: string; authorization_status: string; started_at: string; ended_at: string | null
  meter_start_wh: string; meter_stop_wh: string | null; energy_kwh: string | null
  latest_meter_wh: string | null; latest_meter_at: string | null; stop_reason: string | null; review_reasons: string[]
}
interface Page<T> { items: T[]; total: number; page: number; total_pages: number }
interface Card { id: string; tag_tail: string; driver_email: string; status: string; expires_at: string | null }
interface Sample { timestamp: string; measurand: string; phase: string; location: string; value: string; unit: string }
interface Pending { id: string; charge_point_code: string; action: string; reason: string; transaction_id: number | null; received_at: string }
const clock = (value: string | null) => value ? new Date(value).toLocaleString('vi-VN') : '—'
const number = (value: string | number | null) => value === null ? '—' : Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 3 })
const reviews: Record<string, string> = {
  authorization_blocked: 'Thẻ hoặc tài khoản bị khóa, hoặc trạm không hoạt động', authorization_invalid: 'Thẻ không hợp lệ', authorization_expired: 'Thẻ hết hạn',
  replaced_open_session: 'Đầu nối nhận phiên mới khi phiên cũ chưa đóng', stop_meter_below_start: 'Số đo cuối nhỏ hơn số đo đầu',
  meter_regression: 'Số đo điện năng giảm', conflicting_meter_timestamp: 'Hai số đo khác nhau cùng mốc thời gian', stop_before_start: 'Thời điểm kết thúc trước lúc bắt đầu', reservation_not_verified: 'Mã đặt chỗ chưa được đối chiếu',
  negative_start_meter: 'Số đo bắt đầu không hợp lệ',
}
const quantities: Record<string, string> = { 'Energy.Active.Import.Register': 'Điện năng tích lũy', 'Power.Active.Import': 'Công suất nạp', 'Power.Offered': 'Công suất cấp', 'Current.Import': 'Dòng điện', Voltage: 'Điện áp', SoC: 'Mức pin', Frequency: 'Tần số', Temperature: 'Nhiệt độ' }
const reasons: Record<string, string> = { no_matching_open_session: 'Không khớp phiên đang mở', unknown_transaction: 'Không tìm thấy phiên', already_closed_transaction: 'Phiên đã kết thúc' }
const stopReasons: Record<string, string> = { Local: 'Dừng tại trụ', EVDisconnected: 'Xe ngắt kết nối', Remote: 'Dừng từ xa', EmergencyStop: 'Dừng khẩn cấp', PowerLoss: 'Mất điện', Reboot: 'Khởi động lại', HardReset: 'Khởi động cứng', SoftReset: 'Khởi động mềm', UnlockCommand: 'Mở khóa đầu nối', DeAuthorized: 'Thu hồi xác thực', Other: 'Lý do khác', ReplacedByNewTransaction: 'Bị thay bởi phiên mới' }

async function request<T>(path: string, signal?: AbortSignal, options?: RequestInit): Promise<T> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
  const response = await fetch(`${base}/api/v1/charging${path}`, { credentials: 'include', signal, ...options })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown }
    throw new Error(typeof body.detail === 'string' ? body.detail : response.status === 403 ? 'Bạn không có quyền thực hiện thao tác này.' : 'Không tải được dữ liệu. Hãy thử lại.')
  }
  return await response.json() as T
}

export function ChargingSessionsPage() {
  const [mode, setMode] = useState<'sessions' | 'cards' | 'pending'>('sessions')
  const [state, setState] = useState('all')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<Session> | null>(null)
  const [cards, setCards] = useState<Card[]>([])
  const [pending, setPending] = useState<Pending[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [samples, setSamples] = useState<Page<Sample> | null>(null)
  const [samplePage, setSamplePage] = useState(1)
  const [sampleError, setSampleError] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const [updated, setUpdated] = useState<string | null>(null)
  const [tag, setTag] = useState('')
  const [email, setEmail] = useState('')
  const [expiry, setExpiry] = useState('')
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [mutationError, setMutationError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running) return
      running = true
      try {
        if (mode === 'sessions') {
          const value = await request<Page<Session>>(`/sessions?page=${page}&state=${state}`, controller.signal)
          if (!controller.signal.aborted) setData(value)
        } else if (mode === 'cards') {
          const value = await request<Card[]>('/cards', controller.signal)
          if (!controller.signal.aborted) setCards(value)
        } else {
          const value = await request<Pending[]>('/pending', controller.signal)
          if (!controller.signal.aborted) setPending(value)
        }
        if (!controller.signal.aborted) { setError(''); setLoading(false); setUpdated(new Date().toISOString()) }
      } catch (err) { if (!controller.signal.aborted) { setError(err instanceof Error ? err.message : 'Không tải được dữ liệu.'); setLoading(false) } }
      finally { running = false }
    }
    const first = window.setTimeout(() => { setLoading(true); void load() }, 0)
    const timer = window.setInterval(() => { if (!document.hidden) void load() }, 1000)
    return () => { controller.abort(); window.clearTimeout(first); window.clearInterval(timer) }
  }, [mode, state, page, revision])

  useEffect(() => {
    if (selected === null) return
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running) return
      running = true
      try {
        const value = await request<Page<Sample>>(`/sessions/${selected}/samples?page=${samplePage}&page_size=100`, controller.signal)
        if (!controller.signal.aborted) { setSamples(value); setSampleError('') }
      } catch (err) { if (!controller.signal.aborted) setSampleError(err instanceof Error ? err.message : 'Không tải được số đo.') }
      finally { running = false }
    }
    void load()
    const timer = window.setInterval(() => { if (!document.hidden) void load() }, 1000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [selected, samplePage, revision])

  async function createCard(event: FormEvent) {
    event.preventDefault(); setSaving(true); setMutationError(''); setNotice('')
    try {
      await request<Card>('/cards', undefined, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id_tag: tag, driver_email: email, expires_at: expiry ? new Date(expiry).toISOString() : null }) })
      setTag(''); setEmail(''); setExpiry(''); setNotice('Đã cấp thẻ. Hãy dùng mã thẻ đã nhập để quẹt tại trụ.'); setRevision(r => r + 1)
    } catch (err) { setMutationError(err instanceof Error ? err.message : 'Không cấp được thẻ.') }
    finally { setSaving(false) }
  }
  async function toggleCard(card: Card) {
    setSaving(true); setMutationError(''); setNotice('')
    try {
      await request<Card>(`/cards/${card.id}`, undefined, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: card.status === 'active' ? 'blocked' : 'active' }) })
      setNotice('Đã cập nhật trạng thái thẻ.'); setRevision(r => r + 1)
    } catch (err) { setMutationError(err instanceof Error ? err.message : 'Không cập nhật được thẻ.') }
    finally { setSaving(false) }
  }
  const chooseMode = (value: typeof mode) => { setMode(value); setSelected(null); setNotice(''); setMutationError(''); setError('') }

  return <section className="workspace charging-workspace" aria-labelledby="charging-title">
    <header className="page-heading"><div><h1 id="charging-title">Phiên sạc</h1></div><button className="secondary-button" onClick={() => setRevision(r => r + 1)}>Làm mới</button></header>
    <nav className="charging-tabs" aria-label="Quản lý phiên sạc">{([['sessions', 'Danh sách phiên'], ['cards', 'Thẻ tài xế'], ['pending', 'Chờ đối chiếu']] as const).map(([value, label]) => <button key={value} className="text-button" aria-pressed={mode === value} onClick={() => chooseMode(value)}>{label}</button>)}</nav>
    <p className="ocpp-refresh-note">{error ? 'Mất cập nhật · Dữ liệu có thể đã cũ.' : 'Tự cập nhật mỗi giây'}{updated ? ` · Cập nhật lúc ${clock(updated)}` : ''}</p>
    {error && <div className="form-submit-error" role="alert">{error}<button className="secondary-button" onClick={() => setRevision(r => r + 1)}>Thử lại</button></div>}
    {notice && <p role="status">{notice}</p>}{mutationError && <p className="form-submit-error" role="alert">{mutationError}</p>}
    {mode === 'sessions' && <>
      <div className="ocpp-toolbar"><label>Trạng thái phiên<select value={state} onChange={e => { setState(e.target.value); setPage(1); setData(null); setSelected(null) }}><option value="all">Tất cả</option><option value="open">Đang mở</option><option value="closed">Đã kết thúc</option><option value="review">Cần xem xét</option></select></label><span>{data?.total ?? 0} phiên</span></div>
      {loading && !data && <p>Đang tải phiên sạc…</p>}
      {!loading && !error && data?.items.length === 0 && <p>Chưa có phiên phù hợp. Phiên được tạo khi trụ gửi bản tin bắt đầu sạc.</p>}
      {data?.items.map(item => <article className="charging-session" key={item.id}>
        <div className="ocpp-row__heading"><div><h2>Phiên #{item.id}</h2><p>{item.station_name} · {item.charge_point_code} · Đầu nối {item.connector_number}</p></div><div className="charging-badges"><span className={`status-badge status-badge--${item.ended_at ? 'inactive' : 'active'}`}>{item.ended_at ? 'Đã kết thúc' : 'Đang mở'}</span>{item.review_reasons.length > 0 && <span className="status-badge status-badge--blocked">Cần xem xét</span>}</div></div>
        <dl className="ocpp-facts"><div><dt>Bắt đầu</dt><dd>{clock(item.started_at)}</dd></div><div><dt>Kết thúc</dt><dd>{clock(item.ended_at)}</dd></div><div><dt>Điện năng chốt</dt><dd>{item.energy_kwh !== null ? `${number(item.energy_kwh)} kWh` : 'Chưa chốt'}</dd></div></dl>
        {item.review_reasons.length > 0 && <ul className="charging-review" aria-label={`Lý do xem xét phiên ${item.id}`}>{item.review_reasons.map(reason => <li key={reason}>{reviews[reason] ?? reason}</li>)}</ul>}
        <button className="text-button" aria-expanded={selected === item.id} onClick={() => { setSelected(selected === item.id ? null : item.id); setSamples(null); setSampleError(''); setSamplePage(1) }}>{selected === item.id ? 'Ẩn biểu đồ' : `Xem biểu đồ phiên ${item.id}`}</button>
        {selected === item.id && <div className="charging-detail">
          {sampleError && <p role="alert">{sampleError}</p>}{!samples && !sampleError && <p>Đang tải biểu đồ…</p>}
          {samples && <MeterChart key={`${item.id}-${samplePage}`} readings={samples.items} sessionId={item.id} />}
          <details className="charging-technical"><summary>Thông tin phiên và bảng số đo</summary>
          <dl className="ocpp-facts"><div><dt>Thẻ</dt><dd>…{item.tag_tail}</dd></div><div><dt>Xác thực lúc bắt đầu</dt><dd>{({ Accepted: 'Hợp lệ', Blocked: 'Bị khóa', Expired: 'Hết hạn', Invalid: 'Không hợp lệ' } as Record<string, string>)[item.authorization_status] ?? item.authorization_status}</dd></div><div><dt>Số đo đầu / cuối</dt><dd>{number(item.meter_start_wh)} / {number(item.meter_stop_wh)} Wh</dd></div><div><dt>Lý do kết thúc</dt><dd>{item.stop_reason ? stopReasons[item.stop_reason] ?? item.stop_reason : 'Chưa kết thúc'}</dd></div></dl>
          {samples && samples.items.length > 0 && <div className="charging-table-scroll"><table className="charging-table"><caption>Số đo của phiên #{item.id}</caption><thead><tr><th>Thời điểm trụ ghi</th><th>Đại lượng</th><th>Giá trị</th></tr></thead><tbody>{samples.items.map((sample, i) => <tr key={`${sample.timestamp}-${sample.measurand}-${sample.phase}-${i}`}><td>{clock(sample.timestamp)}</td><td>{quantities[sample.measurand] ?? sample.measurand}{sample.phase ? ` · ${sample.phase}` : ''}{sample.location !== 'Outlet' ? ` · ${sample.location}` : ''}</td><td>{number(sample.value)} {sample.unit}</td></tr>)}</tbody></table></div>}
          </details>
          {samples && samples.total_pages > 1 && <div className="charging-pagination"><button className="secondary-button" disabled={samplePage === 1} onClick={() => { setSamplePage(p => p - 1); setSamples(null) }}>Số đo trước</button><span>Trang {samplePage} / {samples.total_pages}</span><button className="secondary-button" disabled={samplePage >= samples.total_pages} onClick={() => { setSamplePage(p => p + 1); setSamples(null) }}>Số đo tiếp</button></div>}
        </div>}
      </article>)}
      {data && data.total_pages > 1 && <nav className="charging-pagination" aria-label="Phân trang phiên"><button className="secondary-button" disabled={page === 1} onClick={() => { setPage(p => p - 1); setData(null); setSelected(null) }}>Trang trước</button><span>Trang {page} / {data.total_pages}</span><button className="secondary-button" disabled={page >= data.total_pages} onClick={() => { setPage(p => p + 1); setData(null); setSelected(null) }}>Trang sau</button></nav>}
    </>}
    {mode === 'cards' && <>
      <h2>Cấp thẻ cho tài xế</h2><p>Nhập email tài khoản tài xế đang hoạt động. Mã thẻ chỉ hiển thị bốn ký tự cuối sau khi lưu.</p>
      <form className="station-form charging-card-form" onSubmit={event => void createCard(event)}><div className="form-field"><label htmlFor="card-tag">Mã thẻ</label><input id="card-tag" type="password" autoComplete="off" required maxLength={20} value={tag} onChange={e => setTag(e.target.value)} /></div><div className="form-field"><label htmlFor="card-email">Email tài xế</label><input id="card-email" type="email" required value={email} onChange={e => setEmail(e.target.value)} /></div><div className="form-field"><label htmlFor="card-expiry">Hết hạn (không bắt buộc)</label><input id="card-expiry" type="datetime-local" value={expiry} onChange={e => setExpiry(e.target.value)} /></div><div className="station-form__actions"><button className="secondary-button" disabled={saving} type="submit">{saving ? 'Đang lưu…' : 'Cấp thẻ'}</button></div></form>
      <h2>Thẻ trong phạm vi quản lý</h2><p className="ocpp-refresh-note">Hiển thị tối đa 100 thẻ mới nhất.</p>{loading && cards.length === 0 && <p>Đang tải thẻ…</p>}{!loading && !error && cards.length === 0 && <p>Chưa có thẻ được cấp.</p>}
      {cards.map(card => <article className="charging-card-row" key={card.id}><div><strong>Thẻ …{card.tag_tail}</strong><p>{card.driver_email}</p><p>Hết hạn: {card.expires_at ? clock(card.expires_at) : 'Không đặt thời hạn'}</p></div><span className={`status-badge status-badge--${card.status === 'active' ? 'active' : 'blocked'}`}>{card.status === 'blocked' ? 'Đã khóa' : card.expires_at && new Date(card.expires_at) <= new Date() ? 'Hết hạn' : 'Đang hoạt động'}</span><button className="secondary-button" disabled={saving} onClick={() => void toggleCard(card)}>{card.status === 'active' ? 'Khóa thẻ' : 'Mở khóa thẻ'}</button></article>)}
    </>}
    {mode === 'pending' && <><h2>Bản tin chờ đối chiếu</h2><p>Trụ gửi bản tin nhưng chưa khớp phiên. Dữ liệu được giữ để kiểm tra, không tự tạo phiên sạc.</p><p className="ocpp-refresh-note">Hiển thị tối đa 100 bản tin mới nhất.</p>{loading && pending.length === 0 && <p>Đang tải bản tin…</p>}{!loading && !error && pending.length === 0 && <p>Không có bản tin chờ đối chiếu.</p>}{pending.map(item => <article className="charging-session" key={item.id}><h3>{item.charge_point_code} · {item.action}</h3><p>{reasons[item.reason] ?? item.reason}{item.transaction_id ? ` · Phiên #${item.transaction_id}` : ''}</p><p>Nhận lúc {clock(item.received_at)}</p></article>)}</>}
  </section>
}
