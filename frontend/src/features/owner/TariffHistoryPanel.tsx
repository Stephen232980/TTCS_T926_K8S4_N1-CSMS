import { useEffect, useRef, useState } from 'react'
import { StationTariff } from './StationTariff'
import { TariffForm } from './TariffForm'
import { clockText } from './tariffBands'
import { OwnerApiError } from './ownerApi'
import {
  readTariffHistory,
  updateStationTariff,
  type TariffHistory,
  type TariffVersion,
} from './tariffApi'

const statusText = {
  current: 'Đang áp dụng',
  upcoming: 'Sắp hiệu lực',
  historical: 'Đã áp dụng',
}
export function TariffHistoryPanel({ stationId }: { stationId: string }) {
  const [history, setHistory] = useState<TariffHistory | null>(null)
  const [page, setPage] = useState(1)
  const [reload, setReload] = useState(0)
  const [contextRefresh, setContextRefresh] = useState(0)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<TariffVersion | null>(null)
  const [saving, setSaving] = useState(false)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    readTariffHistory(stationId, page, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setHistory(data)
          setError('')
        }
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : 'Không tải được lịch sử biểu giá.',
          )
      })
    return () => {
      mounted.current = false
      controller.abort()
    }
  }, [stationId, page, reload])
  return (
    <>
      <section className="owner-panel owner-tariff-history">
        <h2>Lịch sử phiên bản biểu giá</h2>
        <p className="owner-subtle">
          Phiên bản đã hiệu lực hoặc đã dùng cho hoá đơn được giữ nguyên. Chỉ
          sửa phiên bản chưa hiệu lực và chưa dùng; không xoá phiên bản.
        </p>
        {error && (
          <p className="owner-error" role="alert">
            {error}
            <button
              type="button"
              onClick={() => {
                setError('')
                setHistory(null)
                setReload((value) => value + 1)
              }}
            >
              Tải lại lịch sử
            </button>
          </p>
        )}
        {!history && !error && <p role="status">Đang tải lịch sử biểu giá…</p>}
        {history && (
          <>
            <p className="owner-subtle">
              Ngày tại trạm: {history.today} · {history.timezone}
            </p>
            {history.items.length === 0 && <p>Chưa có phiên bản biểu giá.</p>}
            <ol className="owner-tariff-history-list">
              {history.items.map((version) => (
                <li key={version.id}>
                  <div className="owner-tariff-version-title">
                    <h3>Hiệu lực từ {version.effective_from}</h3>
                    <span>{statusText[version.status]}</span>
                  </div>
                  <ul>
                    {version.bands.map((band) => (
                      <li key={band.start_min}>
                        {clockText(band.start_min)}–{clockText(band.end_min)}:{' '}
                        {BigInt(band.energy_rate_vnd_per_kwh).toLocaleString(
                          'vi-VN',
                        )}{' '}
                        VNĐ/kWh
                      </li>
                    ))}
                  </ul>
                  <p>
                    Phí chiếm trụ:{' '}
                    {BigInt(version.idle_rate_vnd_per_minute).toLocaleString(
                      'vi-VN',
                    )}{' '}
                    VNĐ/phút · Ân hạn: {version.grace_minutes} phút
                  </p>
                  {version.editable ? (
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={saving}
                      aria-label={`Sửa biểu giá ${version.effective_from}`}
                      onClick={() => setEditing(version)}
                    >
                      Sửa phiên bản
                    </button>
                  ) : (
                    <p className="owner-subtle">
                      Không thể sửa: phiên bản đã hiệu lực hoặc đã dùng.
                    </p>
                  )}
                </li>
              ))}
            </ol>
            {history.total > history.page_size && (
              <nav
                className="owner-tariff-history-pages"
                aria-label="Trang lịch sử biểu giá"
              >
                <button
                  className="secondary-button"
                  disabled={page === 1 || saving}
                  onClick={() => {
                    setHistory(null)
                    setEditing(null)
                    setPage((value) => value - 1)
                  }}
                >
                  Trang trước
                </button>
                <span>
                  Trang {page} / {Math.ceil(history.total / history.page_size)}
                </span>
                <button
                  className="secondary-button"
                  disabled={page * history.page_size >= history.total || saving}
                  onClick={() => {
                    setHistory(null)
                    setEditing(null)
                    setPage((value) => value + 1)
                  }}
                >
                  Trang sau
                </button>
              </nav>
            )}
          </>
        )}
      </section>
      {editing && history && (
        <>
          <TariffForm
            key={editing.id}
            currentTariff={null}
            editMode
            initialValues={{
              effectiveFrom: editing.effective_from,
              pricePerKwh: '',
              idleFeePerMinute: editing.idle_rate_vnd_per_minute,
              graceMinutes: String(editing.grace_minutes),
              bands: editing.bands.map((band) => ({
                start: clockText(band.start_min),
                end: clockText(band.end_min),
                price: band.energy_rate_vnd_per_kwh,
                label: band.label,
              })),
            }}
            tariffToday={history.today}
            stationTimezone={history.timezone}
            hasVersions
            onSave={async (values) => {
              setSaving(true)
              try {
                await updateStationTariff(stationId, editing.id, values)
                if (!mounted.current) return
                setHistory(null)
                setEditing(null)
                setReload((value) => value + 1)
                setContextRefresh((value) => value + 1)
              } catch (cause) {
                if (
                  mounted.current &&
                  cause instanceof OwnerApiError &&
                  cause.detail === 'tariff_immutable'
                ) {
                  setHistory(null)
                  setEditing(null)
                  setError(
                    'Phiên bản đã hiệu lực hoặc đã dùng, không thể sửa. Hãy tải lại lịch sử.',
                  )
                }
                throw cause
              } finally {
                if (mounted.current) setSaving(false)
              }
            }}
          />
          <button
            type="button"
            className="secondary-button"
            disabled={saving}
            onClick={() => setEditing(null)}
          >
            Huỷ sửa phiên bản
          </button>
        </>
      )}
      {!editing && (
        <StationTariff
          stationId={stationId}
          refreshKey={contextRefresh}
          onSaved={() => {
            setPage(1)
            setHistory(null)
            setReload((value) => value + 1)
          }}
        />
      )}
    </>
  )
}
