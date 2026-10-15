import { useEffect, useState } from 'react'
import {
  clockText,
  validatePowerBands,
  type PowerBandValues,
} from './powerScheduleBands'
import {
  fetchCurrentPowerLimit,
  fetchPowerSchedule,
  savePowerSchedule,
  type CurrentPowerLimitResponse,
} from './powerScheduleApi'

export function StationPowerScheduleEditor({
  stationId,
}: {
  stationId: string
}) {
  const [effectiveFrom, setEffectiveFrom] = useState(
    new Date().toISOString().split('T')[0],
  )
  const [bands, setBands] = useState<PowerBandValues[]>([
    { start: '00:00', end: '24:00', power_kw: '50' },
  ])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null)
  const [currentLimit, setCurrentLimit] = useState<CurrentPowerLimitResponse | null>(null)

  const { errors, segments, valid } = validatePowerBands(bands)

  useEffect(() => {
    let active = true
    const loadSchedule = async () => {
      setLoading(true)
      try {
        const [schedule, current] = await Promise.all([
          fetchPowerSchedule(stationId, effectiveFrom),
          fetchCurrentPowerLimit(stationId),
        ])
        if (!active) return
        setCurrentLimit(current)
        if (schedule && schedule.bands.length > 0) {
          setBands(
            schedule.bands.map((b) => ({
              start: b.start_time,
              end: b.end_time,
              power_kw: b.power_limit_kw,
            })),
          )
        }
      } catch (err: unknown) {
        if (active) console.error('Error loading power schedule:', err)
      } finally {
        if (active) setLoading(false)
      }
    }
    void loadSchedule()

    return () => {
      active = false
    }
  }, [stationId, effectiveFrom])

  const handleAddBand = () => {
    setBands([...bands, { start: '00:00', end: '24:00', power_kw: '30' }])
  }

  const handleRemoveBand = (index: number) => {
    if (bands.length <= 1) return
    setBands(bands.filter((_, i) => i !== index))
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!valid) return

    setSaving(true)
    setMessage(null)
    try {
      await savePowerSchedule(stationId, effectiveFrom, bands)
      setMessage({ text: 'Lưu lịch công suất thành công!', type: 'success' })
      const updatedLimit = await fetchCurrentPowerLimit(stationId)
      setCurrentLimit(updatedLimit)
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Lỗi lưu lịch công suất'
      setMessage({ text: errorMsg, type: 'error' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="owner-power-schedule-card">
      <div className="owner-section-header">
        <div>
          <h3>Lịch hạn mức công suất theo giờ (S-45)</h3>
          <p className="owner-subtle">
            Đặt trần công suất theo từng khung giờ trong ngày để giảm chi phí giờ cao điểm.
          </p>
        </div>
        {currentLimit && currentLimit.power_limit_kw && (
          <div className="owner-badge owner-badge-active">
            Đang áp dụng: <strong>{currentLimit.power_limit_kw} kW</strong> ({currentLimit.local_time} {currentLimit.timezone})
          </div>
        )}
      </div>

      {message && (
        <div
          className={`owner-feedback ${message.type === 'success' ? 'owner-feedback-success' : 'owner-feedback-error'}`}
        >
          {message.text}
        </div>
      )}

      {loading ? (
        <div className="owner-loading">Đang tải lịch công suất...</div>
      ) : (
        <form onSubmit={handleSave} className="owner-power-form">
          <div className="owner-field">
            <label htmlFor="power-effective-from">Ngày bắt đầu hiệu lực:</label>
            <input
              id="power-effective-from"
              type="date"
              value={effectiveFrom}
              onChange={(e) => setEffectiveFrom(e.target.value)}
              disabled={saving}
              required
            />
          </div>

          <fieldset className="owner-tariff-bands" disabled={saving}>
            <legend>Các khung giờ và công suất trần</legend>
            <p className="owner-subtle">
              Thời gian dạng HH:MM theo múi giờ trạm. Dùng 24:00 cho mốc hết ngày.
            </p>

            {bands.map((band, idx) => {
              const rowErrors = errors[idx] || []
              return (
                <div className="owner-band-row" key={idx}>
                  <strong>Khung {idx + 1}</strong>
                  <div className="owner-band-fields">
                    <label className="owner-field">
                      Từ giờ
                      <input
                        type="text"
                        value={band.start}
                        placeholder="00:00"
                        onChange={(e) =>
                          setBands(
                            bands.map((b, i) =>
                              i === idx ? { ...b, start: e.target.value } : b,
                            ),
                          )
                        }
                      />
                    </label>

                    <label className="owner-field">
                      Đến giờ
                      <input
                        type="text"
                        value={band.end}
                        placeholder="24:00"
                        onChange={(e) =>
                          setBands(
                            bands.map((b, i) =>
                              i === idx ? { ...b, end: e.target.value } : b,
                            ),
                          )
                        }
                      />
                    </label>

                    <label className="owner-field">
                      Hạn mức (kW)
                      <input
                        type="number"
                        step="0.001"
                        min="0.001"
                        value={band.power_kw}
                        placeholder="50"
                        onChange={(e) =>
                          setBands(
                            bands.map((b, i) =>
                              i === idx ? { ...b, power_kw: e.target.value } : b,
                            ),
                          )
                        }
                      />
                    </label>

                    {bands.length > 1 && (
                      <button
                        type="button"
                        className="owner-btn-secondary"
                        onClick={() => handleRemoveBand(idx)}
                      >
                        Xóa
                      </button>
                    )}
                  </div>

                  {rowErrors.length > 0 && (
                    <div className="owner-error-list">
                      {rowErrors.map((err, errIdx) => (
                        <div key={errIdx} className="owner-field-error">
                          {err}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}

            <div className="owner-band-actions">
              <button
                type="button"
                className="owner-btn-secondary"
                onClick={handleAddBand}
                disabled={saving}
              >
                + Thêm khung giờ
              </button>
            </div>
          </fieldset>

          <div className="owner-segments-summary">
            <strong>Độ phủ 24 giờ: </strong>
            {valid ? (
              <span className="owner-text-success">Đã phủ kín 24h không hở/chồng</span>
            ) : (
              <span className="owner-text-error">Chưa phủ kín 24 giờ hợp lệ</span>
            )}
            <div className="owner-segments-bar">
              {segments.map((seg, idx) => (
                <div
                  key={idx}
                  className={`owner-segment-chunk ${seg.rows.length === 1 ? 'owner-segment-ok' : seg.rows.length === 0 ? 'owner-segment-gap' : 'owner-segment-overlap'}`}
                  style={{ width: `${((seg.end - seg.start) / 1440) * 100}%` }}
                  title={`${clockText(seg.start)}–${clockText(seg.end)}: ${seg.rows.length === 1 ? 'OK' : seg.rows.length === 0 ? 'Hở' : 'Chồng'}`}
                />
              ))}
            </div>
          </div>

          <div className="owner-form-footer">
            <button
              type="submit"
              className="owner-btn-primary"
              disabled={!valid || saving}
            >
              {saving ? 'Đang lưu...' : 'Lưu lịch công suất'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
