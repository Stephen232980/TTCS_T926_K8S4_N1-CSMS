import { useEffect, useState, type FormEvent } from 'react'
import {
  createReconciliationRun,
  energy,
  getReconciliationRunDetail,
  getReconciliationRunIssues,
  getReconciliationRuns,
  instant,
  issueCategoryLabels,
  money,
  type ReconciliationIssueItem,
  type ReconciliationRunItem,
  type StationOption,
} from './financeApi'

interface Props {
  stations: StationOption[]
}

export function ReconciliationRunsView({ stations }: Props) {
  const [revision, setRevision] = useState(0)
  const [runsRecord, setRunsRecord] = useState<{ items?: ReconciliationRunItem[]; error?: string }>()
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [detailRecord, setDetailRecord] = useState<{ item?: ReconciliationRunItem; error?: string }>()
  const [issuesRecord, setIssuesRecord] = useState<{ items?: ReconciliationIssueItem[]; total?: number; error?: string }>()
  const [issuesPage, setIssuesPage] = useState(1)
  const [issuesCategory, setIssuesCategory] = useState<string>('')
  const [copiedId, setCopiedId] = useState<string | null>(null)

  // Create form state
  const [formOpen, setFormOpen] = useState(false)
  const todayStr = new Date().toISOString().slice(0, 10)
  const firstOfMonthStr = todayStr.slice(0, 8) + '01'
  const [dateFrom, setDateFrom] = useState(firstOfMonthStr)
  const [dateTo, setDateTo] = useState(todayStr)
  const [filterStationId, setFilterStationId] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    void getReconciliationRuns(undefined, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setRunsRecord({ items: data.items })
      })
      .catch((err) => {
        if (!controller.signal.aborted)
          setRunsRecord({ error: err instanceof Error ? err.message : 'Không tải được danh sách đợt đối soát.' })
      })
    return () => controller.abort()
  }, [revision])

  useEffect(() => {
    if (!selectedRunId) return
    const controller = new AbortController()
    void getReconciliationRunDetail(selectedRunId, controller.signal)
      .then((detail) => {
        if (!controller.signal.aborted) setDetailRecord({ item: detail })
      })
      .catch((err) => {
        if (!controller.signal.aborted)
          setDetailRecord({ error: err instanceof Error ? err.message : 'Không tải được chi tiết đợt đối soát.' })
      })
    void getReconciliationRunIssues(selectedRunId, issuesCategory || undefined, issuesPage, 50, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) setIssuesRecord({ items: res.items, total: res.total })
      })
      .catch((err) => {
        if (!controller.signal.aborted)
          setIssuesRecord({ error: err instanceof Error ? err.message : 'Không tải được danh sách sai lệch.' })
      })
    return () => controller.abort()
  }, [selectedRunId, issuesCategory, issuesPage, revision])

  const runs = runsRecord?.items ?? []
  const loading = !runsRecord
  const error = runsRecord?.error || detailRecord?.error || issuesRecord?.error || ''
  const selectedRun = selectedRunId ? detailRecord?.item : null
  const issues = selectedRunId ? (issuesRecord?.items ?? []) : []
  const issuesTotal = selectedRunId ? (issuesRecord?.total ?? 0) : 0
  const issuesLoading = selectedRunId ? !issuesRecord : false

  const handleCreateRun = async (e: FormEvent) => {
    e.preventDefault()
    if (!dateFrom || !dateTo) {
      setCreateError('Vui lòng chọn đầy đủ ngày bắt đầu và kết thúc.')
      return
    }
    if (dateFrom > dateTo) {
      setCreateError('Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.')
      return
    }
    setCreating(true)
    setCreateError('')
    try {
      const newRun = await createReconciliationRun({
        date_from: dateFrom,
        date_to: dateTo,
        station_id: filterStationId || null,
      })
      setFormOpen(false)
      setRevision((r) => r + 1)
      setSelectedRunId(newRun.id)
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Thực hiện đợt đối soát thất bại.')
    } finally {
      setCreating(false)
    }
  }

  const handleCopyEvidence = async (issue: ReconciliationIssueItem) => {
    const text = `[ĐỐI SOÁT CSMS] Sai lệch Phiên #${issue.session_id}
Loại sai lệch: ${issueCategoryLabels[issue.issue_category] ?? issue.issue_category} (${issue.severity})
Trạm: ${issue.station_name ?? '—'}
Chênh lệch tiền: ${money(issue.discrepancy_amount_vnd)}
Chênh lệch điện: ${energy(issue.discrepancy_kwh)}
Mô tả: ${issue.description}
Bằng chứng: ${JSON.stringify(issue.evidence, null, 2)}`

    try {
      await navigator.clipboard.writeText(text)
      setCopiedId(issue.id)
      setTimeout(() => setCopiedId(null), 3000)
    } catch {
      // Fallback
    }
  }

  return (
    <section className="finance-workspace" aria-labelledby="reconciliation-runs-title">
      <div className="finance-sticky-header">
        <header className="finance-heading">
          <div>
            <h1 id="reconciliation-runs-title">Đợt đối soát tổng kWh & tiền thu (S-53)</h1>
            <p>
              Đối soát bất biến theo mốc cutoff. Dung sai tiền = 0 đồng (tính lại theo biểu giá &amp; quy tắc làm tròn từng dòng).
            </p>
          </div>
          <div className="finance-actions">
            {!selectedRunId && (
              <button
                className="accountant-primary"
                onClick={() => setFormOpen((o) => !o)}
                aria-expanded={formOpen}
              >
                {formOpen ? 'Đóng tạo đợt' : '+ Tạo đợt đối soát mới'}
              </button>
            )}
            <button onClick={() => setRevision((r) => r + 1)}>
              Làm mới
            </button>
          </div>
        </header>

        <p className="finance-readonly">
          Dữ liệu đối soát snapshot là bất biến theo thời điểm chốt (cutoff). Báo cáo phục vụ kiểm toán nội bộ và chuyển vận hành.
        </p>

        {/* Create run modal / inline form */}
        {formOpen && !selectedRunId && (
          <form className="finance-panel finance-create-run-form" onSubmit={handleCreateRun} aria-label="Tạo đợt đối soát mới">
            <h3>Tạo đợt đối soát snapshot mới</h3>
            <p className="finance-filter-note">
              Hệ thống sẽ quét toàn bộ phiên hoàn tất trong khoảng thời gian, tính lại tiền điện theo biểu giá áp dụng và so sánh với hóa đơn, sổ cái ví, công tơ trụ sạc.
            </p>
            <div className="finance-create-fields">
              <label>
                Từ ngày (00:00:00 VN)
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  required
                />
              </label>
              <label>
                Đến ngày (23:59:59 VN)
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  required
                />
              </label>
              <label>
                Lọc theo trạm (tuỳ chọn)
                <select
                  value={filterStationId}
                  onChange={(e) => setFilterStationId(e.target.value)}
                >
                  <option value="">Tất cả các trạm</option>
                  {stations.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {createError && <p className="finance-error" role="alert">{createError}</p>}
            <div className="finance-filter-actions">
              <button className="accountant-primary" type="submit" disabled={creating}>
                {creating ? 'Đang phân tích & tính toán…' : 'Chạy đối soát ngay'}
              </button>
              <button type="button" onClick={() => setFormOpen(false)} disabled={creating}>
                Hủy
              </button>
            </div>
          </form>
        )}
      </div>

      {error && (
        <div className="finance-error" role="alert">
          <p>{error}</p>
          <button onClick={() => setRevision((r) => r + 1)}>
            Thử lại
          </button>
        </div>
      )}

      {loading ? (
        <div className="finance-panel finance-empty" role="status">
          Đang tải dữ liệu đợt đối soát…
        </div>
      ) : selectedRun ? (
        /* DETAIL VIEW OF SELECTED RUN */
        <div className="finance-run-detail-container">
          <div className="finance-detail-heading">
            <button
              className="finance-button navigation-link"
              onClick={() => {
                setSelectedRunId(null)
                setDetailRecord(undefined)
                setIssuesRecord(undefined)
                setIssuesCategory('')
                setIssuesPage(1)
              }}
            >
              ← Quay lại danh sách đợt đối soát
            </button>
            <span className={`finance-status is-${selectedRun.mismatch_sessions > 0 ? 'needs_review' : 'settled'}`}>
              {selectedRun.mismatch_sessions > 0 ? 'Có sai lệch cần xử lý' : 'Khớp 100%'}
            </span>
          </div>

          {/* Meta card */}
          <section className="finance-panel finance-run-meta">
            <div className="finance-section-heading">
              <div>
                <h2>Đợt đối soát #{selectedRun.id.slice(0, 8)}</h2>
                <p>
                  Kỳ đối soát: <strong>{selectedRun.date_from}</strong> → <strong>{selectedRun.date_to}</strong>
                  {selectedRun.station_id ? ` · Trạm lọc: ${selectedRun.station_id}` : ' · Toàn hệ thống'}
                </p>
              </div>
              <div className="finance-code-chip" title="Mã băm dữ liệu đầu vào (SHA-256)">
                Băm bất biến: {selectedRun.input_hash.slice(0, 16)}…
              </div>
            </div>
            <dl className="finance-facts">
              <div>
                <dt>Mốc cutoff</dt>
                <dd>{instant(selectedRun.cutoff_at)}</dd>
              </div>
              <div>
                <dt>Thời gian chạy</dt>
                <dd>{instant(selectedRun.created_at)}</dd>
              </div>
              <div>
                <dt>Trạng thái chạy</dt>
                <dd><strong>{selectedRun.status}</strong></dd>
              </div>
            </dl>
          </section>

          {/* KPI Summary Grid */}
          <section className="finance-summary-grid" aria-label="Tổng quan đợt đối soát">
            <div className="finance-summary-card">
              <span className="finance-summary-label">Phiên sạc</span>
              <strong className="finance-summary-value">{selectedRun.total_sessions.toLocaleString('vi-VN')}</strong>
              <div className="finance-summary-breakdown">
                <span className="finance-badge is-settled">Khớp: {selectedRun.matched_sessions}</span>
                <span className={`finance-badge ${selectedRun.mismatch_sessions > 0 ? 'is-needs_review' : ''}`}>
                  Lệch: {selectedRun.mismatch_sessions}
                </span>
                <span className="finance-badge">Thiếu DL: {selectedRun.missing_data_sessions}</span>
                {selectedRun.exempt_sessions > 0 && (
                  <span className="finance-badge">Miễn trừ: {selectedRun.exempt_sessions}</span>
                )}
              </div>
            </div>

            <div className="finance-summary-card">
              <span className="finance-summary-label">Doanh thu vs Tính lại</span>
              <strong className="finance-summary-value">{money(selectedRun.total_billed_vnd)}</strong>
              <div className="finance-summary-sub">
                <small>Tính lại: {money(selectedRun.total_recomputed_vnd)}</small>
                <small className={Number(selectedRun.money_discrepancy_vnd) > 0 ? 'finance-diff is-warning' : 'finance-diff'}>
                  Lệch: {money(selectedRun.money_discrepancy_vnd)}
                </small>
              </div>
            </div>

            <div className="finance-summary-card">
              <span className="finance-summary-label">Thực thu qua ví</span>
              <strong className="finance-summary-value">{money(selectedRun.total_debited_vnd)}</strong>
              <div className="finance-summary-sub">
                <small>Hóa đơn: {money(selectedRun.total_billed_vnd)}</small>
                <small className={BigInt(selectedRun.total_debited_vnd) !== BigInt(selectedRun.total_billed_vnd) ? 'finance-diff is-warning' : 'finance-diff'}>
                  Lệch ví: {money(String(BigInt(selectedRun.total_billed_vnd) - BigInt(selectedRun.total_debited_vnd)))}
                </small>
              </div>
            </div>

            <div className="finance-summary-card">
              <span className="finance-summary-label">Sản lượng điện</span>
              <strong className="finance-summary-value">{energy(selectedRun.total_meter_kwh)}</strong>
              <div className="finance-summary-sub">
                <small>Hóa đơn: {energy(selectedRun.total_billed_kwh)}</small>
                <small className={Number(selectedRun.kwh_discrepancy) !== 0 ? 'finance-diff is-warning' : 'finance-diff'}>
                  Lệch kWh: {energy(selectedRun.kwh_discrepancy)}
                </small>
              </div>
            </div>
          </section>

          {/* Issue category filter tabs */}
          <section className="finance-panel finance-issues-section" aria-label="Danh sách sai lệch chi tiết">
            <div className="finance-section-heading">
              <h2>Sai lệch &amp; Hồ sơ chuyển vận hành ({issuesTotal.toLocaleString('vi-VN')})</h2>
              <span>Dung sai tiền = 0 VND</span>
            </div>

            <div className="finance-category-tabs" role="tablist">
              <button
                className={`finance-tab ${issuesCategory === '' ? 'is-active' : ''}`}
                onClick={() => {
                  setIssuesCategory('')
                  setIssuesPage(1)
                }}
              >
                Tất cả ({selectedRun.mismatch_sessions})
              </button>
              {Object.entries(selectedRun.summary_counts || {}).map(([cat, cnt]) => (
                <button
                  key={cat}
                  className={`finance-tab ${issuesCategory === cat ? 'is-active' : ''}`}
                  onClick={() => {
                    setIssuesCategory(cat)
                    setIssuesPage(1)
                  }}
                >
                  {issueCategoryLabels[cat] ?? cat} ({cnt})
                </button>
              ))}
            </div>

            {issuesLoading ? (
              <div className="finance-empty" role="status">
                Đang tải danh sách sai lệch…
              </div>
            ) : issues.length === 0 ? (
              <div className="finance-empty">
                <h3>Không phát hiện sai lệch trong nhóm này</h3>
                <p>Tất cả các phiên kiểm tra đều khớp 100% với đơn giá và giao dịch ví.</p>
              </div>
            ) : (
              <div className="finance-table-scroll">
                <table className="finance-session-table">
                  <caption>Chi tiết sai lệch đối soát đợt #{selectedRun.id.slice(0, 8)}</caption>
                  <thead>
                    <tr>
                      <th>Phiên / Trạm</th>
                      <th>Phân loại sai lệch</th>
                      <th>Lệch tiền</th>
                      <th>Lệch điện</th>
                      <th>Mô tả &amp; Bằng chứng</th>
                      <th>Thao tác</th>
                    </tr>
                  </thead>
                  <tbody>
                    {issues.map((issue) => (
                      <tr key={issue.id}>
                        <td>
                          <a
                            className="finance-session-link"
                            href={`#accountant-sessions?session=${issue.session_id}`}
                            title="Xem chi tiết phiên sạc"
                          >
                            Phiên #{issue.session_id}
                          </a>
                          <span>{issue.station_name ?? '—'}</span>
                        </td>
                        <td>
                          <span className={`finance-badge is-severity-${issue.severity}`}>
                            {issueCategoryLabels[issue.issue_category] ?? issue.issue_category}
                          </span>
                        </td>
                        <td className="finance-money">
                          {money(issue.discrepancy_amount_vnd)}
                        </td>
                        <td>
                          {energy(issue.discrepancy_kwh)}
                        </td>
                        <td>
                          <strong>{issue.description}</strong>
                          <details className="finance-evidence-details">
                            <summary>Chi tiết bằng chứng kỹ thuật</summary>
                            <pre>{JSON.stringify(issue.evidence, null, 2)}</pre>
                          </details>
                        </td>
                        <td>
                          <button
                            className="finance-button"
                            onClick={() => handleCopyEvidence(issue)}
                          >
                            {copiedId === issue.id ? '✓ Đã sao chép' : 'Sao chép hồ sơ'}
                          </button>
                          {copiedId === issue.id && (
                            <small className="finance-copied-toast">Đã sao chép để chuyển vận hành</small>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : (
        /* LIST VIEW OF ALL RUNS */
        <section className="finance-panel finance-list-panel" aria-label="Danh sách đợt đối soát">
          <div className="finance-section-heading">
            <h2>{runs.length} đợt đối soát đã thực hiện</h2>
            <span>Mới nhất trước · Bất biến</span>
          </div>

          {runs.length === 0 ? (
            <div className="finance-empty">
              <h3>Chưa có đợt đối soát nào</h3>
              <p>Bấm vào "Tạo đợt đối soát mới" ở trên để chạy snapshot đối soát đầu tiên.</p>
            </div>
          ) : (
            <div className="finance-table-scroll">
              <table className="finance-session-table">
                <caption>Lịch sử các đợt đối soát tài chính</caption>
                <thead>
                  <tr>
                    <th>Đợt đối soát / Mốc Cutoff</th>
                    <th>Khoảng thời gian</th>
                    <th>Phiên sạc</th>
                    <th>Hóa đơn vs Tính lại</th>
                    <th>Lệch tiền</th>
                    <th>Lệch điện</th>
                    <th>Trạng thái</th>
                    <th>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td>
                        <strong>Đợt #{run.id.slice(0, 8)}</strong>
                        <small>{instant(run.cutoff_at)}</small>
                      </td>
                      <td>
                        <span>{run.date_from} → {run.date_to}</span>
                        <small>{run.station_id ? 'Lọc trạm' : 'Toàn hệ thống'}</small>
                      </td>
                      <td>
                        <strong>{run.total_sessions}</strong>
                        <small>Khớp: {run.matched_sessions} · Lệch: {run.mismatch_sessions}</small>
                      </td>
                      <td>
                        <span>HĐ: {money(run.total_billed_vnd)}</span>
                        <small>Tính lại: {money(run.total_recomputed_vnd)}</small>
                      </td>
                      <td className="finance-money">
                        <span className={Number(run.money_discrepancy_vnd) > 0 ? 'finance-diff is-warning' : ''}>
                          {money(run.money_discrepancy_vnd)}
                        </span>
                      </td>
                      <td>
                        {energy(run.kwh_discrepancy)}
                      </td>
                      <td>
                        <span className={`finance-status is-${run.mismatch_sessions > 0 ? 'needs_review' : 'settled'}`}>
                          {run.mismatch_sessions > 0 ? 'Có sai lệch' : 'Khớp 100%'}
                        </span>
                      </td>
                      <td>
                        <button
                          className="finance-button"
                          onClick={() => setSelectedRunId(run.id)}
                        >
                          Xem chi tiết &amp; Sai lệch →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </section>
  )
}
