import { useEffect, useState } from 'react'
import {
  exportOwnerRevenueCsv,
  fetchRevenueReport,
  formatKwh,
  formatVnd,
  type PeriodType,
  type RevenueReportResponse,
} from './ownerRevenueApi'
import type { Station } from '../stations/model/station'
import './ownerRevenueReport.css'

interface OwnerRevenueReportProps {
  stations?: Station[]
  selectedStationId?: string | null
}

export function OwnerRevenueReport({
  stations = [],
  selectedStationId = null,
}: OwnerRevenueReportProps) {
  const [period, setPeriod] = useState<PeriodType>('month')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [stationId, setStationId] = useState<string>(selectedStationId ?? '')
  const [page, setPage] = useState(1)

  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<RevenueReportResponse | null>(null)
  const [refreshCount, setRefreshCount] = useState(0)


  useEffect(() => {
    let ignore = false

    void fetchRevenueReport({
      period,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      station_id: stationId || undefined,
      page,
      page_size: 50,
    })
      .then((data) => {
        if (!ignore) {
          setReport(data)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (!ignore) {
          setError(
            err instanceof Error
              ? err.message
              : 'Không thể tải báo cáo doanh thu. Vui lòng thử lại.',
          )
          setLoading(false)
        }
      })

    return () => {
      ignore = true
    }
  }, [period, dateFrom, dateTo, stationId, page, refreshCount])

  const handlePeriodChange = (newPeriod: PeriodType) => {
    setLoading(true)
    setPeriod(newPeriod)
    setPage(1)
  }

  const handleReload = () => {
    setLoading(true)
    setError(null)
    setRefreshCount((c) => c + 1)
  }

  const handleExportCsv = async () => {
    try {
      setExporting(true)
      await exportOwnerRevenueCsv({
        period,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        station_id: stationId || undefined,
      })
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Xuất CSV thất bại. Vui lòng thử lại.',
      )
    } finally {
      setExporting(false)
    }
  }


  // Daily timeline max calculation for bar height
  const maxInvoice = report?.daily_timeline
    ? Math.max(1, ...report.daily_timeline.map((d) => d.invoice_vnd))
    : 1

  return (
    <div className="owner-revenue-container" data-testid="owner-revenue-report">
      {/* 1. Filter Toolbar */}
      <div className="owner-revenue-toolbar">
        <div className="owner-revenue-period-group" role="group" aria-label="Kỳ báo cáo">
          <button
            type="button"
            className={`owner-period-btn ${period === 'day' ? 'active' : ''}`}
            onClick={() => handlePeriodChange('day')}
          >
            Hôm nay
          </button>
          <button
            type="button"
            className={`owner-period-btn ${period === 'week' ? 'active' : ''}`}
            onClick={() => handlePeriodChange('week')}
          >
            Tuần này
          </button>
          <button
            type="button"
            className={`owner-period-btn ${period === 'month' ? 'active' : ''}`}
            onClick={() => handlePeriodChange('month')}
          >
            Tháng này
          </button>
          <button
            type="button"
            className={`owner-period-btn ${period === 'custom' ? 'active' : ''}`}
            onClick={() => handlePeriodChange('custom')}
          >
            Tùy chọn
          </button>
        </div>

        <div className="owner-revenue-filters">
          {period === 'custom' && (
            <div className="owner-date-inputs">
              <label>
                Từ{' '}
                <input
                  type="date"
                  aria-label="Từ ngày"
                  value={dateFrom}
                  onChange={(e) => {
                    setDateFrom(e.target.value)
                    setPage(1)
                  }}
                />
              </label>
              <label>
                Đến{' '}
                <input
                  type="date"
                  aria-label="Đến ngày"
                  value={dateTo}
                  onChange={(e) => {
                    setDateTo(e.target.value)
                    setPage(1)
                  }}
                />
              </label>
            </div>
          )}

          {stations.length > 0 && (
            <select
              aria-label="Chọn trạm"
              className="owner-station-select"
              value={stationId}
              onChange={(e) => {
                setStationId(e.target.value)
                setPage(1)
              }}
            >
              <option value="">Tất cả các trạm</option>
              {stations.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}

          <button
            type="button"
            className="secondary-button"
            onClick={handleReload}
            aria-label="Làm mới báo cáo"
            disabled={loading}
          >
            Làm mới
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={handleExportCsv}
            aria-label="Xuất CSV báo cáo doanh thu"
            disabled={loading || exporting}
          >
            {exporting ? 'Đang xuất…' : 'Xuất CSV'}
          </button>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div role="alert" className="owner-error">
          <p>{error}</p>
          <button type="button" onClick={handleReload}>
            Thử lại
          </button>
        </div>
      )}

      {/* Loading state indicator */}
      {loading && !report && (
        <div role="status" className="owner-panel owner-placeholder">
          <p>Đang tải dữ liệu báo cáo doanh thu…</p>
        </div>
      )}

      {/* 2. KPI Summary Cards */}
      {report && (
        <>
          <div className="owner-revenue-cards">
            {/* Card 1: Revenue & debits */}
            <div className="owner-metric-card">
              <span className="owner-metric-title">Tổng doanh thu hóa đơn</span>
              <span className="owner-metric-value">
                {formatVnd(report.summary.total_invoice_vnd)}
              </span>
              <div className="owner-metric-subtext">
                <div>
                  <span className="owner-badge success">Đã trừ ví kỳ này</span>{' '}
                  <strong>{formatVnd(report.summary.debited_vnd)}</strong>
                </div>
                <div>
                  <span className="owner-badge pending">Chờ settlement</span>{' '}
                  <strong>{formatVnd(report.summary.awaiting_settlement_vnd)}</strong>{' '}
                  <span className="owner-subtle">
                    ({report.summary.awaiting_settlement_sessions ?? 0} phiên)
                  </span>
                </div>
                {Boolean(report.summary.legacy_exempt_sessions) && (
                  <div>
                    <span className="owner-badge subtle">Miễn trừ cũ</span>{' '}
                    <strong>{formatVnd(report.summary.legacy_exempt_vnd ?? 0)}</strong>{' '}
                    <span className="owner-subtle">
                      ({report.summary.legacy_exempt_sessions} phiên)
                    </span>
                  </div>
                )}
                {Boolean(report.summary.free_sessions) && (
                  <div>
                    <span className="owner-badge subtle">Phiên miễn phí</span>{' '}
                    <strong>{report.summary.free_sessions} phiên</strong>
                  </div>
                )}
              </div>
            </div>

            {/* Card 2: Energy & Sessions */}
            <div className="owner-metric-card secondary">
              <span className="owner-metric-title">Tổng sản lượng điện</span>
              <span className="owner-metric-value">
                {formatKwh(report.summary.total_kwh)}
              </span>
              <div className="owner-metric-subtext">
                <div>
                  Số phiên đã lập hóa đơn:{' '}
                  <strong>{report.summary.invoiced_sessions} phiên</strong>
                </div>
              </div>
            </div>

            {/* Card 3: Fee Breakdown */}
            <div className="owner-metric-card info">
              <span className="owner-metric-title">Cơ cấu doanh thu & phí</span>
              <span className="owner-metric-value">
                {formatVnd(report.summary.energy_amount_vnd)}
              </span>
              <div className="owner-metric-subtext">
                <div>Tiền điện năng: <strong>{formatVnd(report.summary.energy_amount_vnd)}</strong></div>
                <div>Phí quá giờ: <strong>{formatVnd(report.summary.idle_amount_vnd)}</strong></div>
                <div>Phí giữ chỗ (No-show): <strong>{formatVnd(report.summary.reservation_fee_vnd ?? 0)}</strong> <span className="owner-subtle">({report.summary.reservation_count ?? 0} lượt)</span></div>
              </div>
            </div>

            {/* Card 4: Unbilled Operations */}
            <div className="owner-metric-card warning">
              <span className="owner-metric-title">Sản lượng chưa lập HĐ</span>
              <span className="owner-metric-value">
                {formatKwh(report.summary.unbilled_operating_kwh)}
              </span>
              <div className="owner-metric-subtext">
                <div>
                  Phiên hoàn tất chưa xuất HĐ:{' '}
                  <strong>{report.summary.unbilled_sessions} phiên</strong>
                </div>
                {Boolean(report.summary.unbilled_missing_meter_sessions) && (
                  <div>
                    <span className="owner-badge warning">
                      Thiếu số đo: {report.summary.unbilled_missing_meter_sessions} phiên
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* 3. Daily Timeline Bar Chart */}
          {report.daily_timeline.length > 0 && (
            <div className="owner-revenue-chart-card">
              <div className="owner-chart-header">
                <h3>Diễn biến doanh thu theo ngày</h3>
                <span className="owner-subtle">
                  Múi giờ {report.timezone}
                </span>
              </div>
              <div className="owner-timeline-bars" role="region" aria-label="Biểu đồ theo ngày">
                {report.daily_timeline.map((d) => {
                  const heightPercent = Math.max(
                    3,
                    Math.round((d.invoice_vnd / maxInvoice) * 100),
                  )
                  const dayParts = d.date.split('-')
                  const label = `${dayParts[2]}/${dayParts[1]}`
                  return (
                    <div
                      key={d.date}
                      className="owner-bar-col"
                      tabIndex={0}
                      aria-label={`${d.date}: ${formatVnd(d.invoice_vnd)}, ${formatKwh(d.kwh)}`}
                    >
                      <div
                        className="owner-bar"
                        style={{ height: `${heightPercent}%` }}
                      />
                      <span className="owner-bar-date">{label}</span>
                      <div className="owner-bar-tooltip">
                        <strong>{d.date}</strong>
                        <div>Doanh thu: {formatVnd(d.invoice_vnd)}</div>
                        <div>Đã trừ ví: {formatVnd(d.debited_vnd)}</div>
                        {Boolean(d.reservation_fee_vnd) && (
                          <div>Phí giữ chỗ: {formatVnd(d.reservation_fee_vnd ?? 0)}</div>
                        )}
                        <div>Sản lượng: {formatKwh(d.kwh)}</div>
                        <div>Số phiên: {d.sessions_count}</div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* 4. Charge Points Table */}
          <div className="owner-revenue-table-card">
            <div className="owner-table-header">
              <h3>Báo cáo chi tiết theo từng trụ sạc</h3>
              <span className="owner-subtle">
                Tổng cộng {report.pagination.total_items} trụ
              </span>
            </div>
            <div className="owner-revenue-table-wrap">
              <table className="owner-revenue-table">
                <thead>
                  <tr>
                    <th>Trạm</th>
                    <th>Mã trụ</th>
                    <th className="num">Số phiên</th>
                    <th className="num">Sản lượng</th>
                    <th className="num">Tiền điện</th>
                    <th className="num">Phí quá giờ</th>
                    <th className="num">Tổng hóa đơn</th>
                    <th className="num">Đã trừ ví</th>
                    <th className="num">Chờ thu</th>
                    <th className="num">Phí đặt chỗ</th>
                    <th className="num">Chưa lập HĐ</th>
                  </tr>
                </thead>
                <tbody>
                  {report.charge_points.length === 0 ? (
                    <tr>
                      <td colSpan={11} className="owner-empty-row">
                        Không có dữ liệu phiên sạc hoặc doanh thu trong kỳ đã chọn.
                      </td>
                    </tr>
                  ) : (
                    report.charge_points.map((cp) => (
                      <tr key={cp.charge_point_id}>
                        <td>{cp.station_name}</td>
                        <td>
                          <span className="owner-cp-code">{cp.charge_point_code}</span>
                        </td>
                        <td className="num">{cp.sessions_count}</td>
                        <td className="num">{formatKwh(cp.energy_kwh)}</td>
                        <td className="num">{formatVnd(cp.energy_amount_vnd)}</td>
                        <td className="num">{formatVnd(cp.idle_amount_vnd)}</td>
                        <td className="num">
                          <strong>{formatVnd(cp.total_invoice_vnd)}</strong>
                        </td>
                        <td className="num">{formatVnd(cp.debited_vnd)}</td>
                        <td className="num">
                          {cp.awaiting_settlement_vnd > 0 ? (
                            <span className="owner-badge pending">
                              {formatVnd(cp.awaiting_settlement_vnd)}
                            </span>
                          ) : (
                            '0 ₫'
                          )}
                        </td>
                        <td className="num">
                          {(cp.reservation_fee_vnd ?? 0) > 0 ? (
                            <span>{formatVnd(cp.reservation_fee_vnd ?? 0)}</span>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td className="num">
                          {cp.unbilled_sessions > 0 ? (
                            <span>
                              {formatKwh(cp.unbilled_operating_kwh)} ({cp.unbilled_sessions} phiên)
                              {Boolean(cp.unbilled_missing_meter_sessions) && (
                                <span className="owner-badge warning" style={{ marginLeft: 4 }}>
                                  Thiếu {cp.unbilled_missing_meter_sessions}
                                </span>
                              )}
                            </span>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {report.pagination.total_pages > 1 && (
              <div className="owner-table-pagination">
                <span>
                  Trang {report.pagination.page} / {report.pagination.total_pages} (Tổng {report.pagination.total_items} trụ)
                </span>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    type="button"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    Trước
                  </button>
                  <button
                    type="button"
                    disabled={page >= report.pagination.total_pages}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Sau
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
