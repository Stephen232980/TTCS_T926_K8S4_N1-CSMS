import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ControlAction } from '../ocpp/ControlAction'
import { ManualCloseForm } from '../charging/ManualCloseForm'
import { MeterChart } from '../charging/MeterChart'
import { Icon } from '../../components/icons/Icon'
import {
  clock,
  measurementLabels,
  reviewLabels,
  pendingLabels,
  historyLabels,
  decimal,
  groupBy,
  jsonBody,
  ownerRequest,
  type OwnerCard,
  type OwnerPage,
  type OwnerPending,
  type OwnerSession,
  type MeterSample,
} from './ownerApi'
import { ChargerDrawing, Steps } from './OwnerVisuals'

export function OwnerCharging({ initialSessionId, onInitialSessionOpened, area = '', initialState = 'all' }: { initialSessionId?: number; onInitialSessionOpened?: () => void; area?: '' | 'ops'; initialState?: string } = {}) {
  const request = useCallback(<T,>(path: string, options?: RequestInit) => ownerRequest<T>(`${area ? '/' + area : ''}${path}`, options), [area])
  const [closing, setClosing] = useState(false)
  const [mode, setMode] = useState<'sessions' | 'cards' | 'pending'>('sessions')
  const [state, setState] = useState(initialState)
  const [page, setPage] = useState(1)
  const [revision, setRevision] = useState(0)
  const [sessions, setSessions] = useState<OwnerPage<OwnerSession> | null>(null)
  const [cards, setCards] = useState<OwnerCard[]>([])
  const [cardObservedAt, setCardObservedAt] = useState(0)
  const [pending, setPending] = useState<OwnerPending[]>([])
  const [selected, setSelected] = useState<OwnerSession | null>(null)
  const [detailTab, setDetailTab] = useState<'samples' | 'history'>('samples')
  const [samples, setSamples] = useState<OwnerPage<MeterSample> | null>(null)
  const [latestSamples, setLatestSamples] = useState<MeterSample[]>([])
  const [samplePage, setSamplePage] = useState(1)
  const [events, setEvents] = useState<
    {
      id: string
      action: string
      occurred_at: string
      details: { reason?: string }
    }[]
  >([])
  const [eventsSessionId, setEventsSessionId] = useState<number>()
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [detailError, setDetailError] = useState('')
  const [loading, setLoading] = useState(true)
  const [wizard, setWizard] = useState(false)
  const [step, setStep] = useState(0)
  const [tag, setTag] = useState('')
  const [email, setEmail] = useState('')
  const [expiry, setExpiry] = useState('')
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [stationFilter, setStationFilter] = useState('')
  const [sessionObservedAt, setSessionObservedAt] = useState(() => Date.now())
  const selectedId = selected?.id ?? initialSessionId
  useEffect(() => {
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running || wizard) return
      running = true
      try {
        if (mode === 'sessions') {
          const value = await request<OwnerPage<OwnerSession>>(
              `/charging/sessions?page=${page}&page_size=20&state=${state}`,
              { signal: controller.signal },
            )
          if (!controller.signal.aborted) { setSessions(value); setSessionObservedAt(Date.now()) }
          if (selectedId !== undefined) {
            let fresh = value.items.find(item => item.id === selectedId)
            // Closure can move a session outside the current filter or page.
            // The backend currently exposes only a scoped paginated collection.
            for (let lookupPage = 1, totalPages = 1; !fresh && lookupPage <= totalPages; lookupPage++) {
              const all = await request<OwnerPage<OwnerSession>>(
                `/charging/sessions?page=${lookupPage}&page_size=100&state=all`,
                { signal: controller.signal },
              )
              totalPages = all.total_pages
              fresh = all.items.find(item => item.id === selectedId)
            }
            if (!controller.signal.aborted) {
              if (fresh) setSelected(current => current?.id === selectedId || (!current && initialSessionId === selectedId) ? fresh! : current)
              else {
                setSelected(current => current?.id === selectedId ? null : current)
                setNotice('Phiên không còn trong dữ liệu bạn được phép xem.')
              }
              if (initialSessionId !== undefined) onInitialSessionOpened?.()
            }
          }
        }
        else if (mode === 'cards') {
          const value = await request<OwnerCard[]>('/charging/cards', { signal: controller.signal })
          if (!controller.signal.aborted) { setCards(value); setCardObservedAt(Date.now()) }
        } else {
          const value = await request<OwnerPending[]>('/charging/pending', { signal: controller.signal })
          if (!controller.signal.aborted) setPending(value)
        }
        if (!controller.signal.aborted) {
          setError('')
          setLoading(false)
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(
            err instanceof Error ? err.message : 'Không tải được dữ liệu.',
          )
          setLoading(false)
        }
      } finally {
        running = false
      }
    }
    void load()
    const timer = window.setInterval(() => {
      if (!document.hidden && !wizard) void load()
    }, 5000)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [mode, page, state, revision, wizard, selectedId, initialSessionId, onInitialSessionOpened, request])
  useEffect(() => {
    if (selectedId === undefined) return
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running) return
      running = true
      try {
        if (detailTab === 'samples') {
          const value = await request<OwnerPage<MeterSample>>(
            `/charging/sessions/${selectedId}/samples?page=${samplePage}&page_size=100`,
            { signal: controller.signal },
          )
          const latest = samplePage === 1 ? value : await request<OwnerPage<MeterSample>>(
            `/charging/sessions/${selectedId}/samples?page=1&page_size=100`,
            { signal: controller.signal },
          )
          if (!controller.signal.aborted) { setSamples(value); setLatestSamples(latest.items) }
        } else {
          const value = await request<typeof events>(
            `/charging/sessions/${selectedId}/events`,
            { signal: controller.signal },
          )
          if (!controller.signal.aborted) { setEvents(value); setEventsSessionId(selectedId) }
        }
        if (!controller.signal.aborted) setDetailError('')
      } catch (err) {
        if (!controller.signal.aborted)
          setDetailError(
            err instanceof Error ? err.message : 'Không tải được chi tiết.',
          )
      } finally {
        running = false
      }
    }
    void load()
    const timer = window.setInterval(() => { if (!document.hidden) void load() }, 5000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [selectedId, detailTab, samplePage, revision, request])
  async function issue(event: FormEvent) {
    event.preventDefault()
    if (saving) return
    setActionError('')
    if (!tag.trim() || !email.trim()) {
      setActionError('Nhập mã thẻ và email tài xế trước khi cấp.')
      setStep(0)
      return
    }
    if (step === 0) {
      setStep(1)
      return
    }
    setSaving(true)
    try {
      await request(
        '/charging/cards',
        jsonBody('POST', {
          id_tag: tag.trim(),
          driver_email: email.trim(),
          expires_at: expiry ? new Date(expiry).toISOString() : null,
        }),
      )
      setWizard(false)
      setNotice(
        'Đã cấp thẻ. Dùng mã đã nhập trong trụ giả lập để thử luồng sạc.',
      )
      setTag('')
      setEmail('')
      setExpiry('')
      setRevision((value) => value + 1)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Không cấp được thẻ.')
    } finally {
      setSaving(false)
    }
  }
  async function toggle(card: OwnerCard) {
    if (saving) return
    setSaving(true)
    setActionError('')
    try {
      await request(
        `/charging/cards/${encodeURIComponent(card.id)}`,
        jsonBody('PATCH', {
          status: card.status === 'active' ? 'blocked' : 'active',
        }),
      )
      setNotice('Đã cập nhật trạng thái thẻ.')
      setRevision((value) => value + 1)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Chưa cập nhật được thẻ.')
    } finally {
      setSaving(false)
    }
  }
  const operatorSessions = (sessions?.items ?? []).filter(item => (!stationFilter || item.station_name === stationFilter) && `${item.station_name} ${item.charge_point_code} ${item.id}`.toLocaleLowerCase('vi-VN').includes(search.toLocaleLowerCase('vi-VN')))
  const groups = groupBy(sessions?.items ?? [], (item) => item.station_name)
  const visibleCards = cards.filter((card) =>
    card.driver_email.toLowerCase().includes(search.toLowerCase()),
  )
  const drivers = groupBy(visibleCards, (card) => card.driver_email)
  return (
    <section className={`owner-page${selected ? ' owner-session-page' : ''}`}>
      <nav className="owner-tabs" aria-label="Quản lý phiên sạc">
        {(
          [
            ['sessions', 'Phiên sạc'],
            ['cards', 'Thẻ tài xế'],
            ['pending', 'Chờ đối chiếu'],
          ] as const
        ).filter(([key]) => !area || key !== 'cards').map(([key, label]) => (
          <button
            key={key}
            aria-pressed={mode === key}
            onClick={() => {
              setMode(key)
              setSelected(null)
              setWizard(false)
              setPage(1)
              setError('')
              setActionError('')
              setSearch('')
              setLoading(true)
              setNotice('')
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      <header className="owner-heading">
        <div>
          <h1>
            {wizard
              ? 'Cấp thẻ tài xế'
              : selected
                ? `Phiên #${selected.id}`
                : mode === 'sessions'
                  ? 'Phiên sạc'
                  : mode === 'cards'
                    ? 'Thẻ tài xế'
                    : 'Chờ đối chiếu'}
          </h1>
          <p>
            {selected
              ? `${selected.station_name} · ${selected.charge_point_code} · Đầu nối ${selected.connector_number}`
              : area ? 'Theo dõi phiên sạc toàn hệ thống.' : 'Theo dõi trong phạm vi trạm của bạn.'}
          </p>
        </div>
        {selected ? (
          <button
            className="secondary-button"
            onClick={() => {
              setSelected(null)
              setClosing(false)
              setSamples(null)
            }}
          >
            Quay lại danh sách phiên
          </button>
        ) : mode === 'cards' && !wizard ? (
          <button
            className="primary-button"
            onClick={() => {
              setWizard(true)
              setStep(0)
              setError('')
              setActionError('')
            }}
          >
            <Icon name="plus" />
            Cấp thẻ
          </button>
        ) : null}
      </header>
      {error && (!selected || error !== detailError) && (
        <div role="alert" className="owner-error">
          {error}
          <button
            className="text-button"
            onClick={() => setRevision((value) => value + 1)}
          >
            Thử lại
          </button>
        </div>
      )}
      {notice && (
        <p role="status" className="owner-notice">
          {notice}
        </p>
      )}
      {actionError && <p role="alert" className="owner-error">{actionError} {wizard ? 'Kiểm tra thông tin rồi bấm Cấp thẻ để thử lại.' : 'Bấm lại thao tác trên thẻ để thử lại.'}</p>}
      {wizard ? (
        <>
          <Steps labels={['Thông tin thẻ', 'Kiểm tra & cấp']} step={step} />
          <form
            id="owner-card-form"
            className="owner-panel owner-grow owner-two-column"
            onSubmit={(event) => void issue(event)}
          >
            <div>
              {step === 0 ? (
                <>
                  <h2>Nhập thông tin thẻ</h2>
                  <label className="owner-field">
                    Mã thẻ
                    <input
                      required
                      minLength={1}
                      maxLength={20}
                      value={tag}
                      disabled={saving}
                      onChange={(event) => setTag(event.target.value)}
                    />
                  </label>
                  <p>
                    Tự nhập mã thử, dùng cùng mã trong trụ giả lập. Hệ thống
                    không tự đọc hay tự điền mã.
                  </p>
                  <label className="owner-field">
                    Email tài xế
                    <input
                      required
                      type="email"
                      maxLength={320}
                      value={email}
                      disabled={saving}
                      onChange={(event) => setEmail(event.target.value)}
                    />
                  </label>
                  <p>Tài khoản phải đang hoạt động và có vai trò tài xế.</p>
                  <label className="owner-field">
                    Hết hạn · tùy chọn
                    <input
                      type="datetime-local"
                      value={expiry}
                      disabled={saving}
                      onChange={(event) => setExpiry(event.target.value)}
                    />
                  </label>
                </>
              ) : (
                <>
                  <h2>Kiểm tra trước khi cấp</h2>
                  <dl className="owner-review">
                    <div>
                      <dt>Mã thẻ</dt>
                      <dd>{tag}</dd>
                    </div>
                    <div>
                      <dt>Tài xế</dt>
                      <dd>{email}</dd>
                    </div>
                    <div>
                      <dt>Hết hạn</dt>
                      <dd>
                        {expiry
                          ? clock(new Date(expiry).toISOString())
                          : 'Không đặt thời hạn'}
                      </dd>
                    </div>
                  </dl>
                  <p>
                    Ghi lại mã thử để dùng trong trụ giả lập. Sau khi cấp, danh
                    sách chỉ hiển thị phần cuối mã thẻ.
                  </p>
                </>
              )}
            </div>
            <div className="owner-device-preview">
              <Icon name="session" />
              <h3>Gắn đúng thẻ với đúng tài xế</h3>
              <p>Không tạo tài khoản tài xế tại màn hình này.</p>
            </div>
          </form>
          <footer className="owner-actions">
            <button
              className="secondary-button"
              disabled={saving}
              onClick={() => {
                setWizard(false)
                setError('')
                setActionError('')
              }}
            >
              Hủy
            </button>
            <div>
              {step > 0 && (
                <button
                  className="secondary-button"
                  disabled={saving}
                  onClick={() => setStep(0)}
                >
                  Quay lại
                </button>
              )}
              <button
                className="primary-button"
                form="owner-card-form"
                disabled={saving}
              >
                {saving ? 'Đang cấp…' : step ? 'Cấp thẻ' : 'Tiếp tục'}
              </button>
            </div>
          </footer>
        </>
      ) : selected ? (
        <>
          <div className="owner-session-content">
          {area === 'ops' && !selected.ended_at && <div className="operator-session-controls">
            <ControlAction key={selected.id} sessionId={selected.id} label={`#${selected.id}`} onDone={() => setRevision(value => value + 1)} />
            {selected.abnormal_since && <button className="secondary-button" onClick={() => setClosing(true)}>Đóng hồ sơ phiên</button>}
          </div>}
          {closing && area === 'ops' && !selected.ended_at && <ManualCloseForm key={selected.id} sessionId={selected.id} latestMeter={selected.latest_meter_wh} startMeter={selected.meter_start_wh} meterAt={selected.latest_meter_at} onCancel={() => setClosing(false)} onSubmit={async reason => {
            await ownerRequest(`/charging/sessions/${selected.id}/close`, jsonBody('POST', { reason }))
            setClosing(false); setRevision(value => value + 1); setNotice('Đã đóng hồ sơ phiên bằng số đo cuối. Trụ không nhận lệnh dừng sạc.')
          }} />}

          <div className="owner-session-facts owner-panel">
            <div>
              <span>Bắt đầu</span>
              <strong>{clock(selected.started_at)}</strong>
            </div>
            <div>
              <span>Kết thúc</span>
              <strong>
                {selected.ended_at ? clock(selected.ended_at) : 'Đang mở'}
              </strong>
            </div>
            <div>
              <span>{selected.ended_at ? 'Điện năng chốt' : 'Điện đã cấp'}</span>
              <strong>{decimal(selected.ended_at ? selected.energy_kwh : selected.latest_meter_wh !== null && Number(selected.latest_meter_wh) >= Number(selected.meter_start_wh) ? (Number(selected.latest_meter_wh) - Number(selected.meter_start_wh)) / 1000 : null)} kWh</strong>
              {!selected.ended_at && <small>Chốt điện năng khi kết thúc phiên.</small>}
            </div>
            <div>
              <span>Thẻ</span>
              <strong>•••• {selected.tag_tail}</strong>
            </div>
          </div>
          {detailTab === 'samples' && <div className="owner-live-readings owner-panel" aria-label="Số đo mới nhất">
            {[
              { key: 'Power.Active.Import', label: 'Công suất', units: ['W', 'kW'], unit: 'kW' },
              { key: 'Temperature', label: 'Nhiệt độ', units: ['Celsius', 'Celcius'], unit: '°C' },
              { key: 'Voltage', label: 'Điện áp', units: ['V'], unit: 'V' },
              { key: 'Current.Import', label: 'Dòng điện', units: ['A'], unit: 'A' },
            ].map(metric => {
              const reading = latestSamples.filter(item => item.measurand === metric.key && !item.phase && metric.units.includes(item.unit) && item.value.trim() !== '' && Number.isFinite(Number(item.value))).sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0]
              return <div key={metric.key}><span>{metric.label}</span><strong>{reading ? decimal(Number(reading.value) / (reading.unit === 'W' ? 1000 : 1)) : '—'} <small>{metric.unit}</small></strong><small>{reading ? `${clock(reading.timestamp)} · ${reading.location || 'Chưa rõ vị trí'}` : 'Chưa nhận số đo tổng'}</small></div>
            })}
          </div>}
          {selected.review_reasons.length > 0 && (
            <p className="owner-error">
              Cần kiểm tra · {selected.review_reasons.map(reason => reviewLabels[reason] ?? reason).join(', ')}
            </p>
          )}
          <nav className="owner-tabs">
            <button
              aria-pressed={detailTab === 'samples'}
              onClick={() => setDetailTab('samples')}
            >
              Số đo
            </button>
            <button
              aria-pressed={detailTab === 'history'}
              onClick={() => setDetailTab('history')}
            >
              Lịch sử phục hồi
            </button>
          </nav>
          <div className={`owner-panel owner-scroll owner-grow${detailTab === 'samples' ? ' owner-measurements' : ''}${detailError ? ' owner-detail-failed' : ''}`}>
            {detailError && (
              <p role="alert" className="owner-measurement-error">
                <span>{detailError}{detailTab === 'samples' && samples ? ' Đang giữ số đo của lần tải thành công trước.' : ''}</span>
                <button className="secondary-button" onClick={() => setRevision((value) => value + 1)}>
                  Tải lại
                </button>
              </p>
            )}
            {detailTab === 'samples' ? (
              samples && samples.page === samplePage ? (
                <div className="owner-session-data">
                  <MeterChart
                    readings={samples.items}
                    sessionId={selected.id}
                    expanded
                  />
                  <div className="owner-sample-table"><h3>Số đo nhận được</h3><table className="owner-table">
                    <thead>
                      <tr>
                        <th>Thời điểm</th>
                        <th>Số đo</th>
                        <th>Giá trị</th>
                        <th>Pha / vị trí</th>
                      </tr>
                    </thead>
                    <tbody>
                      {samples.items.map((sample, index) => (
                        <tr key={index}>
                          <td>{clock(sample.timestamp)}</td>
                          <td>{measurementLabels[sample.measurand] ?? sample.measurand}</td>
                          <td>
                            {decimal(sample.value)} {['Celsius', 'Celcius'].includes(sample.unit) ? '°C' : sample.unit}
                          </td>
                          <td>
                            {sample.phase || '—'} / {sample.location || '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!samples.items.length && (
                    <p>Chưa nhận số đo cho phiên này.</p>
                  )}
                  </div>
                </div>
              ) : (
                <p role="status">Đang tải số đo…</p>
              )
            ) : eventsSessionId !== selected.id ? (
              !detailError && <p role="status">Đang tải lịch sử phục hồi…</p>
            ) : events.length ? (
              <ol className="owner-history">
                {events.map((event) => (
                  <li key={event.id}>
                    <strong>{historyLabels[event.action] ?? event.action}</strong>
                    <p>{clock(event.occurred_at)}</p>
                    {event.details.reason && <p>{event.details.reason}</p>}
                  </li>
                ))}
              </ol>
            ) : (
              <p>Chưa có sự kiện phục hồi.</p>
            )}
          </div>
          </div>
          {detailTab === 'samples' && (
            <footer className="owner-actions">
              <span>
                Trang số đo {samplePage} / {samples?.total_pages || 1}
              </span>
              <div>
                <button
                  className="secondary-button"
                  disabled={samplePage <= 1}
                  onClick={() => setSamplePage((value) => value - 1)}
                >
                  Trước
                </button>
                <button
                  className="secondary-button"
                  disabled={!samples || samplePage >= samples.total_pages}
                  onClick={() => setSamplePage((value) => value + 1)}
                >
                  Sau
                </button>
              </div>
            </footer>
          )}
        </>
      ) : (
        <>
          {area === 'ops' && mode === 'sessions' && <details className="operator-session-guide"><summary>Hướng dẫn thao tác nhanh</summary><p>Chọn một phiên trong danh sách để xem biểu đồ, số đo và lịch sử. Dừng từ xa cần xác nhận; phiên chỉ kết thúc khi trụ gửi tin kết thúc. Phiên bất thường có thể đóng hồ sơ sau khi kiểm tra trụ.</p></details>}
          <div className={`owner-toolbar${area === 'ops' && mode === 'sessions' ? ' operator-session-filters' : ''}`}>
            {area === 'ops' && mode === 'sessions' && <><label className="owner-search"><Icon name="search"/><input type="search" aria-label="Tìm phiên trong trang" placeholder="Tìm trạm hoặc mã trụ trong trang" value={search} onChange={event=>setSearch(event.target.value)}/></label><label>Trạm trong trang <select value={stationFilter} onChange={event=>setStationFilter(event.target.value)}><option value="">Tất cả trạm</option>{Array.from(new Set(sessions?.items.map(item=>item.station_name) ?? [])).sort().map(name=><option key={name} value={name}>{name}</option>)}</select></label></>}

            {mode === 'sessions' ? (
              <label>
                Trạng thái{' '}
                <select
                  value={state}
                  onChange={(event) => {
                    setState(event.target.value)
                    setPage(1)
                    setLoading(true)
                  }}
                >
                  {[
                    ['all', 'Tất cả'],
                    ['open', 'Đang mở'],
                    ['closed', 'Đã kết thúc'],
                    ['review', 'Cần kiểm tra'],
                    ['abnormal', 'Bất thường'],
                  ].map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label className="owner-search">
                <Icon name="search" />
                <input
                  type="search"
                  aria-label={mode === 'cards' ? 'Tìm tài xế' : 'Tìm mã trụ'}
                  placeholder={
                    mode === 'cards' ? 'Tìm email tài xế' : 'Tìm mã trụ'
                  }
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
            )}
            <button
              className="secondary-button"
              onClick={() => setRevision((value) => value + 1)}
            >
              Làm mới
            </button>
          </div>
          <div className="owner-scroll owner-grow" aria-busy={loading}>
            {loading ? (
              <div className="owner-placeholder" role="status">
                Đang tải dữ liệu…
              </div>
            ) : mode === 'sessions' && area === 'ops' ? (
              operatorSessions.length ? <div className="operator-session-list">{operatorSessions.map(session => {
                const energy = session.ended_at ? session.energy_kwh : session.latest_meter_wh !== null && Number(session.latest_meter_wh) >= Number(session.meter_start_wh) ? (Number(session.latest_meter_wh) - Number(session.meter_start_wh)) / 1000 : null
                const duration = Math.max(0, Math.floor(((session.ended_at ? Date.parse(session.ended_at) : sessionObservedAt) - Date.parse(session.started_at)) / 60000))
                const review = session.review_reasons.length > 0
                return <button className="operator-session-row" key={session.id} onClick={()=>{setSelected(session);setSamples(null);setLatestSamples([]);setSamplePage(1);setDetailTab('samples');setDetailError('');setEvents([]);setEventsSessionId(undefined)}}>
                  <span><strong>Phiên #{session.id}</strong><span className={`operator-session-status${review ? ' is-review' : session.ended_at ? ' is-closed' : ''}`}>{review ? 'Cần xem xét' : session.ended_at ? 'Đã kết thúc' : 'Đang mở'}</span></span>
                  <span>{session.station_name} · {session.charge_point_code} · Đầu nối {session.connector_number}</span>
                  <span className="operator-session-summary"><span><b>{decimal(energy)}</b> <small>kWh{session.ended_at ? ' · đã chốt' : ' · điện đã cấp'}</small></span><span><b>{duration}</b> <small>phút</small></span><span>Số đo mới nhất: {clock(session.latest_meter_at)}</span></span>
                </button>
              })}</div> : <div className="owner-placeholder">{search || stationFilter ? 'Không có phiên khớp bộ lọc trong trang này.' : 'Chưa có phiên sạc phù hợp.'}</div>
            ) : mode === 'sessions' ? (
              sessions?.items.length ? (
                Array.from(groups).map(([stationName, items]) => (
                  <section
                    key={stationName}
                    className="owner-panel owner-session-group"
                  >
                    <header>
                      <h2>{stationName}</h2>
                      <span>{items.length} phiên trên trang này</span>
                    </header>
                    <div className="owner-session-grid">
                      {items.map((session) => (
                        <button
                          className="owner-session-card"
                          key={session.id}
                          onClick={() => {
                            setSelected(session)
                            setSamples(null)
                            setLatestSamples([])
                            setSamplePage(1)
                            setDetailTab('samples')
                            setDetailError('')
                            setEvents([])
                            setEventsSessionId(undefined)
                          }}
                        >
                          <ChargerDrawing />
                          <div>
                            <strong>
                              {session.charge_point_code} · Đầu nối{' '}
                              {session.connector_number}
                            </strong>
                            <span>
                              Phiên #{session.id} ·{' '}
                              {session.ended_at ? 'Đã kết thúc' : 'Đang mở'}
                            </span>
                            <span>{clock(session.started_at)}</span>
                            <b>{decimal(session.ended_at ? session.energy_kwh : session.latest_meter_wh !== null && Number(session.latest_meter_wh) >= Number(session.meter_start_wh) ? (Number(session.latest_meter_wh) - Number(session.meter_start_wh)) / 1000 : null)} kWh {session.ended_at ? '· đã chốt' : '· điện đã cấp'}</b>
                            {session.review_reasons.length > 0 && (
                              <span className="owner-attention">
                                Cần kiểm tra
                              </span>
                            )}
                          </div>
                          <Icon name="chevronRight" />
                        </button>
                      ))}
                    </div>
                  </section>
                ))
              ) : (
                <div className="owner-placeholder">
                  Chưa có phiên sạc phù hợp.
                </div>
              )
            ) : mode === 'cards' ? (
              visibleCards.length ? (
                Array.from(drivers).map(([driver, items]) => (
                  <section key={driver} className="owner-panel owner-driver">
                    <h2>{driver}</h2>
                    {items.map((card) => (
                      <div className="owner-card-row" key={card.id}>
                        <Icon name="session" />
                        <div>
                          <strong>•••• {card.tag_tail}</strong>
                          <span>
                            {card.status === 'blocked' ? 'Đã khóa' : card.expires_at && Date.parse(card.expires_at) <= cardObservedAt ? 'Đã hết hạn' : 'Hoạt động'}{' '}
                            ·{' '}
                            {card.expires_at
                              ? `Hết hạn ${clock(card.expires_at)}`
                              : 'Không đặt thời hạn'}
                          </span>
                        </div>
                        <button
                          className="secondary-button"
                          disabled={saving}
                          onClick={() => void toggle(card)}
                        >
                          {card.status === 'active' ? 'Khóa thẻ' : 'Mở khóa'}
                        </button>
                      </div>
                    ))}
                  </section>
                ))
              ) : (
                <div className="owner-placeholder">
                  Chưa có thẻ phù hợp. Cấp thẻ để thử luồng với trụ giả lập.
                </div>
              )
            ) : (
              <div className="owner-panel">
                <table className="owner-table">
                  <thead>
                    <tr>
                      <th>Trụ</th>
                      <th>Bản tin</th>
                      <th>Lý do</th>
                      <th>Phiên</th>
                      <th>Nhận lúc</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pending
                      .filter((item) =>
                        item.charge_point_code
                          .toLowerCase()
                          .includes(search.toLowerCase()),
                      )
                      .map((item) => (
                        <tr key={item.id}>
                          <td>{item.charge_point_code}</td>
                          <td>{item.action}</td>
                          <td>{pendingLabels[item.reason] ?? item.reason}</td>
                          <td>{item.transaction_id ?? '—'}</td>
                          <td>{clock(item.received_at)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
                {!pending.filter(item => item.charge_point_code.toLowerCase().includes(search.toLowerCase())).length && <p>{search ? 'Không có bản tin phù hợp với tìm kiếm.' : 'Không có bản tin chờ đối chiếu.'}</p>}
              </div>
            )}
          </div>
          <footer className="owner-actions">
            <span>
              {mode === 'sessions'
                ? `${sessions?.total ?? 0} phiên · Trang ${page} / ${sessions?.total_pages || 1}${area === 'ops' ? ` · ${operatorSessions.length} phiên hiển thị trên trang` : ''}`
                : mode === 'pending'
                  ? `${pending.length === 100 ? '100 bản tin mới nhất · ' : ''}Bản tin chỉ đọc; hệ thống đối chiếu khi nhận đủ dữ liệu.`
                  : `${visibleCards.length} thẻ${cards.length === 100 ? ' · đang xem 100 thẻ mới nhất' : ''}`}
            </span>
            {mode === 'sessions' && (
              <div>
                <button
                  className="secondary-button"
                  disabled={page <= 1}
                  onClick={() => {
                    setPage((value) => value - 1)
                    setLoading(true)
                  }}
                >
                  Trước
                </button>
                <button
                  className="secondary-button"
                  disabled={!sessions || page >= sessions.total_pages}
                  onClick={() => {
                    setPage((value) => value + 1)
                    setLoading(true)
                  }}
                >
                  Sau
                </button>
              </div>
            )}
          </footer>
        </>
      )}
    </section>
  )
}
