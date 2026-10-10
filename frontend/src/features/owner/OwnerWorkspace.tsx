import { useCallback, useEffect, useRef, useState } from 'react'
import type { AuthenticatedUser } from '../auth/model/auth'
import type { StationApi } from '../stations/api/stationApi'
import { HttpStationApi } from '../stations/api/httpStationApi'
import type {
  Station,
  PaginatedResult,
  StationStatus,
} from '../stations/model/station'
import type { ChargePointApi } from '../chargePoints/api/chargePointApi'
import { HttpChargePointApi } from '../chargePoints/api/httpChargePointApi'
import type {
  ChargePoint,
  ChargePointPage,
  Connector,
} from '../chargePoints/model/chargePoint'
import { Icon, type IconName } from '../../components/icons/Icon'
import { StationWizard } from './StationWizard'
import { ChargerWizard } from './ChargerWizard'
import { OwnerCharging } from './OwnerCharging'
import { TariffHistoryPanel } from './TariffHistoryPanel'
import { ChargerDrawing, ConnectionSymbol, ConnectorSymbol, StationPhoto } from './OwnerVisuals'
import {
  clock,
  decimal,
  statusLabel,
  ownerRequest,
  type Connection,
  type OwnerPage,
  type OwnerSession,
  type MeterSample,
} from './ownerApi'
import './owner.css'

const stationsApi = new HttpStationApi()
const chargersApi = new HttpChargePointApi()
type Area = 'stations' | 'charging' | 'tariffs' | 'revenue' | 'power'
const navigation: { area: Area; label: string; icon: IconName }[] = [
  { area: 'stations', label: 'Trạm của tôi', icon: 'station' },
  { area: 'charging', label: 'Phiên sạc', icon: 'session' },
  { area: 'tariffs', label: 'Biểu giá', icon: 'report' },
  { area: 'revenue', label: 'Doanh thu', icon: 'report' },
  { area: 'power', label: 'Công suất', icon: 'bolt' },
]

export function Telemetry({
  charger,
  connector,
  onSessions,
  reportedStatus,
  online,
}: {
  charger: ChargePoint
  connector: Connector
  onSessions: (id: number) => void
  reportedStatus?: string
  online?: boolean
}) {
  const [data, setData] = useState<{
    session: OwnerSession | null
    samples: MeterSample[]
    observedAt: number
  } | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running) return
      running = true
      try {
        let session: OwnerSession | null = null
        for (let page = 1; ; page++) {
          const result = await ownerRequest<OwnerPage<OwnerSession>>(
            `/charging/sessions?state=open&page_size=100&page=${page}`,
            { signal: controller.signal },
          )
          session =
            result.items.find(
              (item) =>
                item.charge_point_code === charger.code &&
                item.connector_number === connector.connectorNumber,
            ) ?? null
          if (session || page >= result.total_pages) break
        }
        let samples: MeterSample[] = []
        if (session) {
          const first = await ownerRequest<OwnerPage<MeterSample>>(
            `/charging/sessions/${session.id}/samples?page_size=100&page=1`,
            { signal: controller.signal },
          )
          // Samples are newest first; the last page contains the oldest readings.
          samples = first.items
        }
        if (!controller.signal.aborted) {
          setData({ session, samples, observedAt: Date.now() })
          setError('')
        }
      } catch (err) {
        if (!controller.signal.aborted)
          setError(err instanceof Error ? err.message : 'Không tải được số đo.')
      } finally {
        running = false
      }
    }
    void load()
    const timer = window.setInterval(() => {
      if (!document.hidden) void load()
    }, 5000)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [charger.code, connector.connectorNumber, retry])
  const latest = new Map<string, MeterSample>()
  for (const sample of data?.samples ?? []) {
    const key = `${sample.measurand}|${sample.phase}|${sample.location}|${sample.unit}`
    const current = latest.get(key)
    if (!current || sample.timestamp > current.timestamp)
      latest.set(key, sample)
  }
  const labels: Record<string, string> = {
    'Power.Active.Import': 'Công suất',
    Temperature: 'Nhiệt độ',
    Voltage: 'Điện áp',
    'Current.Import': 'Dòng điện',
    SoC: 'Mức pin',
    'Energy.Active.Import.Register': 'Điện năng tích lũy',
  }
  const energy =
    data?.session?.latest_meter_wh != null
      ? (Number(data.session.latest_meter_wh) -
          Number(data.session.meter_start_wh)) /
        1000
      : null
  const power = Array.from(latest.values()).find(
    (sample) =>
      sample.measurand === 'Power.Active.Import' &&
      !sample.phase &&
      ['W', 'kW'].includes(sample.unit),
  )
  const duration = data?.session
    ? Math.max(
        0,
        Math.floor((data.observedAt - Date.parse(data.session.started_at)) / 60000),
      )
    : null
  return (
    <>
      <h3>Số đo phiên đang mở</h3>
      {error && (
        <p role="alert" className="owner-error">
          {error}
          <button onClick={() => setRetry((value) => value + 1)}>
            Thử lại
          </button>
        </p>
      )}
      {!data && !error && <p role="status">Đang tải số đo…</p>}
      {data && !error && (
        <>
          {online === false && <p className="owner-subtle">Trụ ngoại tuyến · số đo dưới đây là lần cuối nhận được, không phải số đo trực tiếp.</p>}
          {!data.session && reportedStatus?.toLowerCase() === 'charging' && <p role="status" className="owner-error">Trụ báo đang sạc nhưng backend chưa ghi nhận phiên đang mở. Đang chờ đồng bộ giao dịch; chưa có số đo phiên để hiển thị.</p>}
          <div className="owner-meter-pair">
            <div>
              <span>Công suất</span>
              <strong>
                {power
                  ? decimal(
                      Number(power.value) / (power.unit === 'W' ? 1000 : 1),
                    )
                  : '—'}{' '}
                <small>kW</small>
              </strong>
              <small>
                {power ? clock(power.timestamp) : 'Chưa có số đo tổng'}
              </small>
            </div>
            <div>
              <span>Điện đã cấp</span>
              <strong>
                {energy !== null && energy >= 0 ? decimal(energy) : '—'}{' '}
                <small>kWh</small>
              </strong>
              <small>{clock(data.session?.latest_meter_at)}</small>
            </div>
            <div>
              <span>Thời gian</span>
              <strong>
                {duration === null ? '—' : decimal(duration)}{' '}
                <small>phút</small>
              </strong>
            </div>
            <div>
              <span>Tiền tạm tính</span>
              <strong>—</strong>
              <small>Chưa có biểu giá</small>
            </div>
          </div>
          {Array.from(latest.values())
            .filter((sample) => labels[sample.measurand] && (sample.phase || !['Power.Active.Import', 'Energy.Active.Import.Register'].includes(sample.measurand)))
            .map((sample) => (
              <div
                className="owner-live-row"
                key={`${sample.measurand}|${sample.phase}|${sample.location}|${sample.unit}`}
              >
                <span>
                  {labels[sample.measurand]}
                  {sample.phase && ` · ${sample.phase}`}
                  {sample.location && ` · ${sample.location}`}
                  <small>{clock(sample.timestamp)}</small>
                </span>
                <strong>
                  {decimal(sample.value)} {['Celsius', 'Celcius'].includes(sample.unit) ? '°C' : sample.unit}
                </strong>
              </div>
            ))}
          {!latest.size && (
            <p>
              Chưa nhận số đo
              {data.session ? ' từ trụ' : ' · đầu nối chưa có phiên đang mở'}.
            </p>
          )}
          {data.session && (
            <>
              <p>Bắt đầu: {clock(data.session.started_at)}</p>
              <button className="secondary-button" onClick={() => onSessions(data.session!.id)}>
                Xem phiên sạc
              </button>
            </>
          )}
        </>
      )}
      <details className="owner-nominal"><summary>Thông số danh định</summary>
      <dl className="owner-facts">
        <div>
          <dt>Loại đầu nối</dt>
          <dd>{connector.connectorType ?? 'Chưa khai báo'}</dd>
        </div>
        <div>
          <dt>Dòng điện</dt>
          <dd>{connector.currentType ?? '—'}</dd>
        </div>
        <div>
          <dt>Công suất</dt>
          <dd>{decimal(connector.maxPowerKw)} kW</dd>
        </div>
        <div>
          <dt>Điện áp / dòng điện</dt>
          <dd>
            {decimal(connector.voltage)} V / {decimal(connector.amperage)} A
          </dd>
        </div>
      </dl></details>
    </>
  )
}

export function OwnerWorkspace({
  currentUser,
  onLogout,
  onAdmin,
  stationApi = stationsApi,
  chargePointApi = chargersApi,
}: {
  currentUser: AuthenticatedUser
  onLogout: () => Promise<void>
  onAdmin?: () => void
  stationApi?: StationApi
  chargePointApi?: ChargePointApi
}) {
  const [area, setArea] = useState<Area>('stations')
  const [stations, setStations] = useState<PaginatedResult<Station> | null>(
    null,
  )
  const [station, setStation] = useState<Station | null>(null)
  const [chargers, setChargers] = useState<ChargePointPage | null>(null)
  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionError, setConnectionError] = useState('')
  const [selected, setSelected] = useState<{
    charger: ChargePoint
    connector: Connector
  } | null>(null)
  const [page, setPage] = useState(1)
  const [chargerPage, setChargerPage] = useState(1)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StationStatus | ''>('')
  const [chargerSearch, setChargerSearch] = useState('')
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState<
    'create-station' | 'edit-station' | 'create-charger' | 'edit-charger' | null
  >(null)
  const [editingCharger, setEditingCharger] = useState<
    ChargePoint | undefined
  >()
  const [notice, setNotice] = useState('')
  const [sessionToOpen, setSessionToOpen] = useState<number>()
  const initialSessionOpened = useCallback(() => setSessionToOpen(undefined), [])
  const [menu, setMenu] = useState(false)
  const [mobile, setMobile] = useState(() => window.matchMedia?.('(max-width: 800px)').matches ?? false)
  const sidebarRef = useRef<HTMLElement>(null)
  const menuRef = useRef<HTMLButtonElement>(null)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  const stationId = station?.id
  useEffect(() => {
    const query = window.matchMedia?.('(max-width: 800px)')
    if (!query) return
    const update = (event: MediaQueryListEvent) => { setMobile(event.matches); if (!event.matches) setMenu(false) }
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    if (!mobile || !menu) return
    const controls = Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>('a, button:not(:disabled)') ?? [])
    controls[0]?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setMenu(false); menuRef.current?.focus(); return }
      if (event.key !== 'Tab' || !controls.length) return
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus() }
      else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0].focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mobile, menu])
  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      void stationApi
        .listStations(
          { page, pageSize: 20, search, ...(status ? { status } : {}) },
          controller.signal,
        )
        .then((value) => {
          if (!controller.signal.aborted) {
            setStations(value)
            setLoading(false)
            setError('')
          }
        })
        .catch((err) => {
          if (!controller.signal.aborted) {
            setLoading(false)
            setError(
              err instanceof Error
                ? 'Không tải được trạm. Hãy thử lại.'
                : 'Không tải được trạm.',
            )
          }
        })
    }, 150)
    return () => {
      controller.abort()
      window.clearTimeout(timeout)
    }
  }, [stationApi, page, search, status, revision])
  useEffect(() => {
    if (!stationId) return
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running) return
      running = true
      try {
        const value = await chargePointApi.listChargePoints(
          stationId!,
          chargerPage,
          20,
          controller.signal,
        )
        if (!controller.signal.aborted) {
          setChargers(value)
          setError('')
        }
        const current = await stationApi.getStation(stationId!, controller.signal)
        if (!controller.signal.aborted) setStation(current)
      } catch {
        if (!controller.signal.aborted)
          setError('Không tải được danh sách trụ. Hãy thử lại.')
      }
      try {
        const items: Connection[] = []
        for (let page = 1; ; page++) {
          const result = await ownerRequest<OwnerPage<Connection>>(
            `/ocpp/connections?page=${page}&page_size=100`,
            { signal: controller.signal },
          )
          items.push(...result.items)
          if (page >= result.total_pages) break
        }
        if (!controller.signal.aborted) {
          setConnections(items)
          setConnectionError('')
        }
      } catch {
        if (!controller.signal.aborted) {
          setConnections([])
          setConnectionError(
            'Chưa tải được kết nối trực tiếp. Trạng thái đầu nối chưa được xác nhận.',
          )
        }
      } finally {
        running = false
      }
    }
    void load()
    const timer = window.setInterval(() => {
      if (!document.hidden && !form) void load()
    }, 5000)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [stationId, stationApi, chargePointApi, chargerPage, revision, form])
  function open(record: Station) {
    setStation(record)
    setChargers(null)
    setSelected(null)
    setChargerPage(1)
    setChargerSearch('')
    setError('')
  }
  async function logout() {
    setLoggingOut(true)
    setLogoutError('')
    try {
      await onLogout()
    } catch {
      setLogoutError('Không đăng xuất được. Hãy thử lại.')
      setLoggingOut(false)
    }
  }
  const selectedCharger =
    selected && chargers?.items.find((item) => item.id === selected.charger.id)
  const selectedConnector = selectedCharger?.connectors.find(
    (item) => item.id === selected?.connector.id,
  )
  const selectedConnection = connections.find(item => item.id === selectedCharger?.id)
  const selectedLive = selectedConnection?.connectors.find(item => item.id === selectedConnector?.id)
  return (
    <div className={`owner-shell${menu ? ' owner-menu-open' : ''}`}>
      <aside ref={sidebarRef} id="owner-navigation" inert={mobile && !menu} className="owner-sidebar" aria-label="Điều hướng chủ trạm">
        <a
          href="#stations"
          className="owner-brand"
          onClick={() => {
            setArea('stations')
            setStation(null)
            setForm(null)
            setMenu(false)
          }}
        >
          <Icon name="bolt" />
          CSMS
        </a>
        <nav>
          {navigation.map((item) => (
            <a
              key={item.area}
              href={`#${item.area}`}
              className={area === item.area ? 'is-active' : ''}
              aria-current={area === item.area ? 'page' : undefined}
              onClick={() => {
                setArea(item.area)
                setForm(null)
                setError('')
                setMenu(false)
              }}
            >
              <Icon name={item.icon} />
              {item.label}
            </a>
          ))}
        </nav>
        <footer>
          <strong>Chủ trạm</strong>
          <span title={currentUser.email}>{currentUser.email}</span>
          {onAdmin && <button onClick={onAdmin}>Đổi khu vực</button>}
          {logoutError && <p role="alert">{logoutError}</p>}
          <button disabled={loggingOut} onClick={() => void logout()}>
            <Icon name="logout" />
            {loggingOut ? 'Đang đăng xuất…' : 'Đăng xuất'}
          </button>
        </footer>
      </aside>
      <main className="owner-main">
        <header className="owner-mobile-bar">
          <button
            ref={menuRef}
            aria-controls="owner-navigation"
            aria-label="Mở hoặc đóng điều hướng"
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            <Icon name={menu ? 'close' : 'menu'} />
          </button>
          <strong>CSMS · Chủ trạm</strong>
        </header>
        {area === 'charging' ? (
          <OwnerCharging initialSessionId={sessionToOpen} onInitialSessionOpened={initialSessionOpened} />
        ) : area !== 'stations' ? (
          <section className="owner-page">
            <header className="owner-heading">
              <div>
                <h1>{navigation.find((item) => item.area === area)?.label}</h1>
                <p>Quản lý trong phạm vi trạm của bạn.</p>
              </div>
            </header>
            <div className="owner-panel owner-placeholder owner-grow">
              <Icon name={area === 'power' ? 'bolt' : 'report'} />
              <h2>
                {area === 'power'
                  ? 'Chưa có chức năng cấu hình công suất'
                  : area === 'tariffs'
                    ? 'Chưa có chức năng biểu giá'
                    : 'Chưa có báo cáo doanh thu'}
              </h2>
              <p>
                {area === 'power'
                  ? 'Thông số công suất danh định và số đo hiện có xem trong chi tiết đầu nối.'
                  : 'Chức năng này sẽ khả dụng khi nghiệp vụ tương ứng được triển khai.'}
              </p>
              <button
                className="secondary-button"
                onClick={() => setArea('stations')}
              >
                Về trạm của tôi
              </button>
            </div>
          </section>
        ) : form === 'create-station' || form === 'edit-station' ? (
          <StationWizard
            key={`${form}-${station?.id ?? ''}`}
            station={
              form === 'edit-station' ? (station ?? undefined) : undefined
            }
            api={stationApi}
            onCancel={() => setForm(null)}
            onSaved={(record) => {
              setForm(null)
              open(record)
              setRevision((value) => value + 1)
              setNotice('Đã lưu thông tin trạm.')
            }}
          />
        ) : (form === 'create-charger' || form === 'edit-charger') &&
          station ? (
          <ChargerWizard
            stationId={station.id}
            charger={editingCharger}
            api={chargePointApi}
            onCancel={() => setForm(null)}
            onSaved={() => {
              setForm(null)
              setRevision((value) => value + 1)
              setNotice('Đã lưu trụ sạc.')
            }}
          />
        ) : (
          <section className="owner-page">
            <header className="owner-heading">
              <div>
                {station && (
                  <button
                    className="text-button"
                    onClick={() => {
                      setStation(null)
                      setSelected(null)
                      setError('')
                    }}
                  >
                    Quay lại danh sách trạm
                  </button>
                )}
                <h1>{station?.name ?? 'Trạm của tôi'}</h1>
                <p>
                  {station?.address ??
                    'Nhận diện và quản lý từng trạm của bạn.'}
                </p>
              </div>
              <div className="owner-heading-actions">
                {station ? (
                  <>
                    <button
                      className="secondary-button"
                      onClick={() => setForm('edit-station')}
                    >
                      <Icon name="edit" />
                      Thông tin trạm
                    </button>
                    <button
                      className="primary-button"
                      onClick={() => {
                        setEditingCharger(undefined)
                        setForm('create-charger')
                      }}
                    >
                      <Icon name="plus" />
                      Thêm trụ
                    </button>
                  </>
                ) : (
                  <button
                    className="primary-button"
                    onClick={() => setForm('create-station')}
                  >
                    <Icon name="plus" />
                    Tạo trạm
                  </button>
                )}
              </div>
            </header>
            {notice && (
              <div role="status" className="owner-notice">
                {notice}
                <button
                  aria-label="Đóng thông báo"
                  onClick={() => setNotice('')}
                >
                  <Icon name="close" />
                </button>
              </div>
            )}
            {error && (
              <div role="alert" className="owner-error">
                {error}
                <button onClick={() => setRevision((value) => value + 1)}>
                  Thử lại
                </button>
              </div>
            )}
            {!station ? (
              <>
                <div className="owner-toolbar">
                  <label className="owner-search">
                    <Icon name="search" />
                    <input
                      type="search"
                      maxLength={100}
                      aria-label="Tìm trạm"
                      placeholder="Tìm tên hoặc địa chỉ trạm"
                      value={search}
                      onChange={(event) => {
                        setSearch(event.target.value)
                        setPage(1)
                        setLoading(true)
                      }}
                    />
                  </label>
                  <label>
                    Trạng thái{' '}
                    <select
                      value={status}
                      onChange={(event) => {
                        setStatus(event.target.value as StationStatus | '')
                        setPage(1)
                        setLoading(true)
                      }}
                    >
                      <option value="">Tất cả</option>
                      {(
                        ['active', 'inactive', 'suspended', 'blocked'] as const
                      ).map((key) => (
                        <option key={key} value={key}>
                          {statusLabel[key]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="secondary-button"
                    onClick={() => setRevision((value) => value + 1)}
                  >
                    Làm mới
                  </button>
                </div>
                <div className="owner-scroll owner-grow">
                  {loading ? (
                    <div className="owner-placeholder" role="status">
                      Đang tải trạm…
                    </div>
                  ) : stations?.items.length ? (
                    <div className="owner-station-grid">
                      {[...stations.items]
                        .sort(
                          (a, b) =>
                            Number(
                              b.status === 'blocked' ||
                                b.status === 'suspended',
                            ) -
                            Number(
                              a.status === 'blocked' ||
                                a.status === 'suspended',
                            ),
                        )
                        .map((record) => (
                          <article
                            className="owner-station-card"
                            key={record.id}
                          >
                            <StationPhoto
                              url={record.photoUrl}
                              name={record.name}
                            />
                            <div>
                              <span
                                className={`owner-station-status status-${record.status}`}
                              >
                                {statusLabel[record.status]}
                              </span>
                              <h2>{record.name}</h2>
                              <p>{record.address}</p>
                              <button
                                className="secondary-button"
                                aria-label={`Xem chi tiết ${record.name}`}
                                onClick={() => open(record)}
                              >
                                Xem trạm
                                <Icon name="chevronRight" />
                              </button>
                            </div>
                          </article>
                        ))}
                    </div>
                  ) : (
                    <div className="owner-placeholder">
                      <Icon name="station" />
                      <h2>Chưa có trạm phù hợp</h2>
                      <p>
                        {search || status
                          ? 'Đổi bộ lọc để tìm trạm khác.'
                          : 'Tạo trạm đầu tiên để bắt đầu quản lý.'}
                      </p>
                    </div>
                  )}
                </div>
                <footer className="owner-actions">
                  <span>
                    {stations?.total ?? 0} trạm · Trang {page} /{' '}
                    {stations?.totalPages || 1}
                  </span>
                  <div>
                    <button
                      className="secondary-button"
                      disabled={page <= 1}
                      onClick={() => {
                        setPage(page - 1)
                        setLoading(true)
                      }}
                    >
                      Trước
                    </button>
                    <button
                      className="secondary-button"
                      disabled={!stations || page >= stations.totalPages}
                      onClick={() => {
                        setPage(page + 1)
                        setLoading(true)
                      }}
                    >
                      Sau
                    </button>
                  </div>
                </footer>
              </>
            ) : (
              <>
                <div className="owner-toolbar owner-statusbar">
                  <strong
                    className={`owner-station-status status-${station.status}`}
                  >
                    {statusLabel[station.status]}
                  </strong>
                  <span>{chargers?.total ?? '—'} trụ</span>
                  <div className="owner-legend">
                    {['available', 'charging', 'faulted', 'unknown'].map(
                      (key) => (
                        <span key={key} className={`connector-${key}`}>
                          <ConnectorSymbol status={key} />
                          {statusLabel[key]}
                        </span>
                      ),
                    )}
                  </div>
                </div>
                {connectionError && (
                  <p className="owner-subtle" role="status">
                    {connectionError}
                  </p>
                )}
                <div className="owner-tariff-scroll">
                  <TariffHistoryPanel key={station.id} stationId={String(station.id)} />
                </div>

                <div className="owner-detail-grid owner-grow">
                  <section className="owner-chargers">
                    <header>
                      <h2>Khu sạc</h2>
                      <input
                        type="search"
                        aria-label="Tìm trụ trên trang"
                        placeholder="Tìm trụ trên trang"
                        value={chargerSearch}
                        onChange={(event) =>
                          setChargerSearch(event.target.value)
                        }
                      />
                    </header>
                    <div className="owner-scroll owner-grow">
                      <div className="owner-charger-grid">
                        {chargers?.items
                          .filter((item) =>
                            `${item.code} ${item.name ?? ''}`
                              .toLowerCase()
                              .includes(chargerSearch.toLowerCase()),
                          )
                          .map((charger) => {
                            const connection = connections.find(
                              (item) => item.id === charger.id,
                            )
                            return (
                              <article
                                key={charger.id}
                                className={`owner-charger-card${selected?.charger.id === charger.id ? ' is-selected' : ''}`}
                              >
                                <header>
                                  <strong>
                                    {charger.name || charger.code}
                                  </strong>
                                  <span
                                    className={`owner-connection ${connection?.online ? 'is-online' : ''}`}
                                    title={
                                      connection
                                        ? `${connection.online ? 'Trực tuyến' : 'Ngoại tuyến'} · ${clock(connection.last_seen_at)}`
                                        : 'Chưa có dữ liệu kết nối'
                                    }
                                  >
                                    <ConnectionSymbol online={connection?.online} />
                                  </span>
                                </header>
                                {charger.name && <small>{charger.code}</small>}
                                <ChargerDrawing online={connection?.online} />
                                <div className="owner-connectors">
                                  {charger.connectors.map((connector) => {
                                    const live = connection?.connectors.find(
                                      (item) => item.id === connector.id,
                                    )
                                    const state = (
                                      live?.raw_ocpp_status ??
                                      live?.status ??
                                      'unknown'
                                    ).toLowerCase()
                                    const label = statusLabel[state] ?? state
                                    return (
                                      <button
                                        key={connector.id}
                                        className={`connector-${state}${selected?.connector.id === connector.id ? ' is-selected' : ''}`}
                                        aria-label={`${charger.code} · Đầu nối ${connector.connectorNumber}: ${label}`}
                                        aria-pressed={
                                          selected?.connector.id ===
                                          connector.id
                                        }
                                        title={`Đầu nối ${connector.connectorNumber}: ${label}`}
                                        onClick={() =>
                                          setSelected({ charger, connector })
                                        }
                                      >
                                        <small>
                                          {connector.connectorNumber}
                                        </small>
                                        <ConnectorSymbol status={state} />
                                      </button>
                                    )
                                  })}
                                </div>
                                <footer>
                                  <span>
                                    {charger.connectors.length} đầu nối
                                  </span>
                                  <button
                                    className="text-button"
                                    aria-label={`Sửa ${charger.code}`}
                                    onClick={() => {
                                      setEditingCharger(charger)
                                      setForm('edit-charger')
                                    }}
                                  >
                                    <Icon name="edit" />
                                    Sửa
                                  </button>
                                </footer>
                              </article>
                            )
                          })}
                      </div>
                      {chargers?.items.length === 0 && (
                        <div className="owner-placeholder">
                          <h2>Chưa có trụ sạc</h2>
                          <p>
                            Thêm trụ để khai báo đầu nối và kết nối thiết bị.
                          </p>
                        </div>
                      )}
                      {!chargers && !error && (
                        <p role="status">Đang tải trụ…</p>
                      )}
                    </div>
                    <footer className="owner-charger-pagination">
                      <span>
                        Trang {chargerPage} / {chargers?.totalPages || 1}
                      </span>
                      <button
                        disabled={chargerPage <= 1}
                        onClick={() => {
                          setChargerPage(chargerPage - 1)
                          setSelected(null)
                        }}
                      >
                        Trước
                      </button>
                      <button
                        disabled={
                          !chargers || chargerPage >= chargers.totalPages
                        }
                        onClick={() => {
                          setChargerPage(chargerPage + 1)
                          setSelected(null)
                        }}
                      >
                        Sau
                      </button>
                    </footer>
                  </section>
                  <aside className="owner-panel owner-detail-panel owner-scroll">
                    {selectedCharger && selectedConnector ? (
                      <>
                        <h2>{selectedCharger.name || selectedCharger.code}</h2>
                        <p>Đầu nối {selectedConnector.connectorNumber}</p>
                        <p className="owner-contact"><ConnectionSymbol online={selectedConnection?.online} /> {selectedConnection ? selectedConnection.online ? 'Trực tuyến' : 'Ngoại tuyến' : 'Chưa có dữ liệu kết nối'}</p>
                        <p className="owner-subtle">Liên lạc cuối: {clock(selectedConnection?.last_seen_at ?? null)}</p>
                        <p>{statusLabel[(selectedLive?.raw_ocpp_status ?? selectedLive?.status ?? 'unknown').toLowerCase()] ?? 'Chưa rõ trạng thái'}</p>
                        {selectedLive?.last_error_code && selectedLive.last_error_code !== 'NoError' && <p className="owner-subtle">Lỗi ghi nhận gần nhất: {selectedLive.last_error_code} · {clock(selectedLive.last_error_at)}</p>}
                        <Telemetry
                          key={selectedConnector.id}
                          charger={selectedCharger}
                          connector={selectedConnector}
                          reportedStatus={selectedLive?.raw_ocpp_status ?? selectedLive?.status}
                          online={selectedConnection?.online}
                          onSessions={(id) => { setSessionToOpen(id); setArea('charging') }}
                        />
                      </>
                    ) : (
                      <div className="owner-placeholder">
                        <Icon name="charger" />
                        <h2>Chọn một đầu nối</h2>
                        <p>Xem số đo phiên sạc và thông số thiết bị tại đây.</p>
                      </div>
                    )}
                  </aside>
                </div>
              </>
            )}
          </section>
        )}
      </main>
    </div>
  )
}
