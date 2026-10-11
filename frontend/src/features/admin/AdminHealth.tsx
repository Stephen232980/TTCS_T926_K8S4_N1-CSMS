import { useEffect, useRef, useState } from 'react'
import {
  adminRequest,
  dateTime,
  numberText,
  healthSegments,
  type Health,
  type HealthHistory,
} from './adminApi'
import { ErrorNotice } from './AdminShared'

type MetricKey =
  | 'online_charge_points'
  | 'running_sessions'
  | 'error_messages_5m'
  | 'response_latency_ms'
const definitions: {
  key: MetricKey
  name: string
  unit: string
  description: string
}[] = [
  {
    key: 'online_charge_points',
    name: 'Trụ trực tuyến',
    unit: 'trụ',
    description:
      'Trụ có Boot hợp lệ, còn trong hạn Heartbeat và thuộc trạm không bị khóa.',
  },
  {
    key: 'running_sessions',
    name: 'Phiên đang sạc',
    unit: 'phiên',
    description:
      'Phiên đang mở, không bất thường; đầu nối báo Charging và trụ còn trực tuyến.',
  },
  {
    key: 'error_messages_5m',
    name: 'Trao đổi OCPP có lỗi',
    unit: 'lượt / 5 phút',
    description:
      'CALLERROR hoặc StatusNotification có mã lỗi. Giá trị của cửa sổ 5 phút tại mỗi mốc, không phải tổng theo giờ.',
  },
  {
    key: 'response_latency_ms',
    name: 'Thời gian phản hồi',
    unit: 'ms',
    description:
      'Trung bình từ lúc backend nhận CALL đến khi gửi xong phản hồi. Không phải thời gian trụ thực thi lệnh.',
  },
]
export function AdminHealth() {
  const [data, setData] = useState<{
    health: Health
    history: HealthHistory
    receivedAt: number
  }>()
  const [error, setError] = useState<unknown>()
  const [busy, setBusy] = useState(false)
  const [paused, setPaused] = useState(false)
  const [resolution, setResolution] = useState(3600)
  const [version, setVersion] = useState(0)
  const [expanded, setExpanded] = useState<MetricKey | null>(null)
  const [now, setNow] = useState(Date.now)
  const manualVersion = useRef(version)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    const manual = manualVersion.current !== version
    manualVersion.current = version
    if (paused && !manual) return
    let timer: ReturnType<typeof setTimeout> | undefined
    let running = false
    async function load() {
      if (running || controller.signal.aborted) return
      running = true
      setBusy(true)
      try {
        const [health, history] = await Promise.all([
          adminRequest<Health>('/admin/system-health', {
            signal: controller.signal,
          }),
          adminRequest<HealthHistory>(
            `/admin/system-health/history?resolution_seconds=${resolution}`,
            { signal: controller.signal },
          ),
        ])
        if (!controller.signal.aborted) {
          setData({ health, history, receivedAt: Date.now() })
          setError(undefined)
        }
        if (!controller.signal.aborted && !paused)
          timer = setTimeout(
            () => {
              if (document.visibilityState !== 'hidden') void load()
            },
            Math.max(1, health.refresh_after_seconds) * 1000,
          )
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err)
          if (!paused)
            timer = setTimeout(() => {
              if (document.visibilityState !== 'hidden') void load()
            }, 30000)
        }
      } finally {
        running = false
        if (!controller.signal.aborted) setBusy(false)
      }
    }
    void load()
    const visible = () => {
      if (document.visibilityState !== 'hidden' && !paused) {
        clearTimeout(timer)
        void load()
      }
    }
    document.addEventListener('visibilitychange', visible)
    return () => {
      controller.abort()
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [paused, resolution, version])
  useEffect(() => {
    if (!expanded) return
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setExpanded(null)
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [expanded])
  const h = data?.health
  const snapshot = h?.snapshot
  // Use server-generated clock plus elapsed local time to avoid workstation clock skew.
  const stale =
    h?.status === 'stale' ||
    (!!snapshot &&
      !!data &&
      Date.parse(h!.generated_at) +
        now -
        data.receivedAt -
        Date.parse(snapshot.collected_at) >
        h!.stale_after_seconds * 1000)
  const metrics = snapshot?.metrics
  return (
    <>
      <header className="admin-heading">
        <div>
          <h1>Sức khỏe hệ thống</h1>
          <p>Theo dõi vận hành và dữ liệu OCPP trong 24 giờ gần nhất.</p>
        </div>
        <div className="admin-actions">
          <button
            aria-pressed={paused}
            onClick={() => {
              setPaused(!paused)
              setBusy(false)
            }}
          >
            {paused ? 'Tiếp tục cập nhật' : 'Tạm dừng cập nhật'}
          </button>
          <button
            className="admin-primary"
            disabled={busy}
            onClick={() => setVersion((v) => v + 1)}
          >
            {busy ? 'Đang cập nhật…' : 'Cập nhật ngay'}
          </button>
        </div>
      </header>
      <ErrorNotice error={error} onRetry={() => setVersion((v) => v + 1)} />
      <div className="admin-health-toolbar">
        <span
          className={`admin-badge ${stale ? 'warning' : snapshot ? 'good' : 'neutral'}`}
        >
          {stale
            ? 'Dữ liệu đã cũ'
            : snapshot
              ? 'Có dữ liệu gần nhất'
              : 'Chưa có dữ liệu'}
        </span>
        <span>
          {snapshot
            ? `Đo lúc ${dateTime(snapshot.collected_at)}`
            : busy
              ? 'Đang tải dữ liệu…'
              : 'Chờ hệ thống thu thập'}
        </span>
        <label>
          Khoảng lấy mẫu
          <select
            value={resolution}
            onChange={(e) => setResolution(Number(e.target.value))}
          >
            <option value={3600}>1 giờ</option>
            <option value={1800}>30 phút</option>
            <option value={300}>5 phút</option>
            <option value={30}>30 giây</option>
          </select>
        </label>
      </div>
      {stale && (
        <p className="admin-inline-warning" role="status">
          Các giá trị dưới đây là dữ liệu lần đo trước. Hãy cập nhật lại để kiểm
          tra.
        </p>
      )}
      {metrics && !metrics.window_complete && (
        <p className="admin-inline-warning">
          Chưa đủ cửa sổ 5 phút. Đã quan sát{' '}
          {numberText(metrics.error_messages_observed_5m)} lượt lỗi và{' '}
          {numberText(metrics.response_count_5m)} phản hồi; chưa coi là số liệu
          đầy đủ.
        </p>
      )}
      <div
        className={`admin-health-grid ${expanded ? 'is-expanded' : ''}`}
        aria-busy={busy}
      >
        {definitions
          .filter((d) => !expanded || d.key === expanded)
          .map((d) => (
            <section className="admin-panel admin-chart-panel" key={d.key}>
              <header>
                <div>
                  <h2>{d.name}</h2>
                  <p className="admin-metric">
                    <strong>{numberText(metrics?.[d.key])}</strong>
                    <span>{d.unit}</span>
                    {d.key === 'online_charge_points' && metrics && (
                      <small>
                        / {numberText(metrics.registered_charge_points)} đã đăng
                        ký
                      </small>
                    )}
                  </p>
                </div>
                <button
                  onClick={() => setExpanded(expanded ? null : d.key)}
                  aria-label={`${expanded ? 'Thu gọn' : 'Phóng to'} ${d.name}`}
                >
                  {expanded ? 'Thu gọn' : 'Phóng to'}
                </button>
              </header>
              <HealthPlot
                history={data?.history}
                metric={d.key}
                name={d.name}
                unit={d.unit}
              />
              <details className="admin-metric-definition">
                <summary>Cách tính</summary>
                <p>{d.description}</p>
                {d.key === 'response_latency_ms' && (
                  <p>
                    {metrics?.response_count_5m ?? 0} mẫu phản hồi trong cửa sổ
                    gần nhất. Không có mẫu thì để trống.
                  </p>
                )}
              </details>
            </section>
          ))}
      </div>
      <footer className="admin-health-footer">
        <span>
          {paused
            ? 'Đã tạm dừng tự cập nhật.'
            : `Tự cập nhật mỗi ${h?.refresh_after_seconds ?? 30} giây.`}{' '}
          Khoảng trống biểu thị chưa có số đo.
        </span>
        <span>
          {data?.history.available_since
            ? `Lịch sử từ ${dateTime(data.history.available_since)}`
            : 'Chưa có lịch sử thu thập'}
        </span>
      </footer>
    </>
  )
}

function HealthPlot({
  history,
  metric,
  name,
  unit,
}: {
  history?: HealthHistory
  metric: MetricKey
  name: string
  unit: string
}) {
  const container = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 440, height: 150 })
  const [inspect, setInspect] = useState<number | null>(null)
  useEffect(() => {
    if (!container.current) return
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0 && entry.contentRect.height > 0)
        setSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        })
    })
    observer.observe(container.current)
    return () => observer.disconnect()
  }, [])
  const segments = healthSegments(history?.points ?? [], metric)
  const values = segments.flat().map((p) => p.value)
  const peak = Math.max(0, ...values)
  const max =
    metric === 'response_latency_ms'
      ? Math.max(1, peak * 1.15)
      : Math.max(2, Math.ceil((peak * 1.15) / 2) * 2)
  const left = 46,
    right = size.width - 12,
    top = 10,
    bottom = Math.max(40, size.height - 25)
  const start = history ? Date.parse(history.from_at) : 0
  const end = history ? Date.parse(history.to_at) : 1
  const x = (time: number) =>
    left + ((time - start) / Math.max(1, end - start)) * (right - left)
  const y = (value: number) => bottom - (value / max) * (bottom - top)
  const selected = inspect == null ? undefined : history?.points[inspect]
  const t = (value: number) =>
    new Date(value).toLocaleTimeString('vi-VN', {
      timeZone: 'Asia/Ho_Chi_Minh',
      hour: '2-digit',
      minute: '2-digit',
    })
  return (
    <div className="admin-plot-wrap">
      <div className="admin-plot" ref={container}>
        <svg
          viewBox={`0 0 ${size.width} ${size.height}`}
          role="img"
          aria-label={`${name}: lịch sử 24 giờ; ${values.length} điểm có dữ liệu`}
        >
          {[0, 0.5, 1].map((r) => (
            <g key={r}>
              <line
                x1={left}
                x2={right}
                y1={y(max * r)}
                y2={y(max * r)}
                stroke="#dce7eb"
              />
              <text x={left - 7} y={y(max * r) + 4} textAnchor="end">
                {numberText(max * r)}
              </text>
            </g>
          ))}
          {history &&
            [start, (start + end) / 2, end].map((time, i) => (
              <text
                key={i}
                x={x(time)}
                y={size.height - 5}
                textAnchor={i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}
              >
                {t(time)}
              </text>
            ))}
          {segments.map((segment, i) => (
            <g key={i}>
              {segment.length > 1 && (
                <polyline
                  points={segment
                    .map((p) => `${x(p.time)},${y(p.value)}`)
                    .join(' ')}
                  fill="none"
                  stroke="#14795e"
                  strokeWidth="2"
                />
              )}
              {segment.map((p) => (
                <circle
                  key={p.time}
                  cx={x(p.time)}
                  cy={y(p.value)}
                  r="3"
                  fill="#14795e"
                >
                  <title>
                    {dateTime(p.measured)} · {numberText(p.value)} {unit}
                  </title>
                </circle>
              ))}
            </g>
          ))}
          {selected && (
            <line
              x1={x(Date.parse(selected.bucket_start))}
              x2={x(Date.parse(selected.bucket_start))}
              y1={top}
              y2={bottom}
              stroke="#526e7b"
              strokeDasharray="4 3"
            />
          )}
        </svg>
        {!values.length && (
          <p className="admin-plot-empty">Chưa có số đo cho chỉ số này.</p>
        )}
      </div>
      {history && (
        <div className="admin-chart-inspect">
          <label>
            <span>Xem mốc</span>
            <input
              aria-label={`Xem mốc ${name}`}
              type="range"
              min={0}
              max={Math.max(0, history.points.length - 1)}
              value={inspect ?? Math.max(0, history.points.length - 1)}
              onChange={(e) => setInspect(Number(e.target.value))}
            />
          </label>
          <output>
            {selected
              ? `${t(Date.parse(selected.bucket_start))} · ${numberText(selected.metrics?.[metric])} ${unit}${selected.measured_at ? ` · đo ${t(Date.parse(selected.measured_at))}` : ' · chưa có số đo'}`
              : 'Chọn mốc để xem số đo'}
          </output>
        </div>
      )}
    </div>
  )
}
