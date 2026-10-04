import { useState, type FormEvent } from 'react'
import type { ChargePointApi } from '../chargePoints/api/chargePointApi'
import type {
  ChargePoint,
  ConnectorConfiguration,
} from '../chargePoints/model/chargePoint'
import { ChargerDrawing, Steps } from './OwnerVisuals'

const connectorTypes = ['Type 2', 'CCS2', 'Type 1', 'CCS1', 'CHAdeMO', 'GB/T AC', 'GB/T DC', 'NACS']

export function ChargerWizard({
  stationId,
  charger,
  api,
  onCancel,
  onSaved,
}: {
  stationId: string
  charger?: ChargePoint
  api: ChargePointApi
  onCancel: () => void
  onSaved: () => void
}) {
  const [step, setStep] = useState(0)
  const [code, setCode] = useState(charger?.code ?? '')
  const [name, setName] = useState(charger?.name ?? '')
  const [count, setCount] = useState(charger?.connectors.length ?? 2)
  const [connectors, setConnectors] = useState<ConnectorConfiguration[]>(
    Array.from({ length: 4 }, (_, index) => {
      const existing = charger?.connectors.find(
        (item) => item.connectorNumber === index + 1,
      )
      return {
        connector_number: index + 1,
        connector_type: existing?.connectorType ?? null,
        current_type: existing?.currentType ?? null,
        max_power_kw: existing?.maxPowerKw ?? null,
        voltage: existing?.voltage ?? null,
        amperage: existing?.amperage ?? null,
      }
    }),
  )
  const [error, setError] = useState('')
  const [customTypes, setCustomTypes] = useState<boolean[]>(connectors.map(item => !!item.connector_type && !connectorTypes.includes(item.connector_type)))
  const [saving, setSaving] = useState(false)
  function patch(
    index: number,
    key: keyof ConnectorConfiguration,
    value: string,
  ) {
    setConnectors((items) =>
      items.map((item, i) =>
        i === index ? { ...item, [key]: value || null } : item,
      ),
    )
  }
  async function next(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSaving(true)
    try {
      if (step === 0 && (!charger || code.trim() !== charger.code)) {
        if (!code.trim() || code.trim().length > 64)
          throw new Error('Mã trụ gồm 1–64 ký tự.')
        const result = await api.checkCodeAvailability(code)
        if (!result.available)
          throw new Error('Mã trụ đã tồn tại. Hãy chọn mã khác.')
      }
      if (step < 2) {
        setStep(step + 1)
        return
      }
      if (charger)
        await api.updateChargePoint(charger.id, {
          ...(code.trim() !== charger.code ? { code: code.trim() } : {}),
          name: name.trim() || null,
          connectors: connectors.slice(0, count),
        })
      else
        await api.createChargePoint(stationId, {
          code: code.trim(),
          name: name.trim() || null,
          connectorCount: count,
          connectors: connectors.slice(0, count),
        })
      onSaved()
    } catch (err) {
      setError(
        err instanceof Error && !err.message.includes('api_error')
          ? err.message
          : 'Chưa lưu được trụ. Kiểm tra mã trụ, thông số và thử lại.',
      )
    } finally {
      setSaving(false)
    }
  }
  return (
    <section className="owner-page owner-wizard">
      <header className="owner-heading">
        <div>
          <h1>{charger ? 'Sửa trụ sạc' : 'Thêm trụ sạc'}</h1>
          <p>Khai báo thiết bị, cấu hình đầu nối rồi kiểm tra.</p>
        </div>
        <button
          className="secondary-button"
          onClick={onCancel}
          disabled={saving}
        >
          Hủy
        </button>
      </header>
      <Steps
        labels={['Thông tin trụ', 'Đầu nối', 'Kiểm tra & lưu']}
        step={step}
      />
      {error && (
        <p role="alert" className="owner-error">
          {error}
        </p>
      )}
      <form
        id="owner-charger-form"
        onSubmit={(event) => void next(event)}
        className="owner-panel owner-grow"
      >
        {step === 0 ? (
          <div className="owner-two-column">
            <div>
              <h2>Thông tin thiết bị</h2>
              <label className="owner-field">
                Mã trụ
                <input
                  required
                  maxLength={64}
                  value={code}
                  disabled={saving || !!charger?.codeLockedAt}
                  onChange={(event) => setCode(event.target.value)}
                />
              </label>
              <p>
                {charger?.codeLockedAt
                  ? 'Mã đã khóa sau khi phát sinh phiên sạc. Bạn vẫn có thể sửa tên và thông số.'
                  : 'Dùng mã này khi kết nối trụ giả lập hoặc thiết bị.'}
              </p>
              <label className="owner-field">
                Tên hiển thị · tùy chọn
                <input
                  maxLength={150}
                  value={name}
                  disabled={saving}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              <label className="owner-field">
                Số đầu nối
                <select
                  value={count}
                  disabled={saving || !!charger}
                  onChange={(event) => setCount(Number(event.target.value))}
                >
                  {[1, 2, 3, 4].map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              {charger && (
                <p>
                  Hãng: {charger.vendor ?? 'Chưa có'} · Model:{' '}
                  {charger.model ?? 'Chưa có'} · Firmware:{' '}
                  {charger.firmwareVersion ?? 'Chưa có'}. Các thông tin này do
                  trụ gửi.
                </p>
              )}
            </div>
            <div className="owner-device-preview">
              <ChargerDrawing />
              <h3>{name || code || 'Trụ của bạn'}</h3>
              <p>{count} đầu nối</p>
            </div>
          </div>
        ) : step === 1 ? (
          <>
            <h2>Thông số đầu nối</h2>
            <p>
              Thông số danh định trên thiết bị, có thể để trống khi chưa biết.
            </p>
            <div className="owner-connector-config">
              {connectors.slice(0, count).map((connector, index) => (
                <fieldset key={connector.connector_number}>
                  <legend>Đầu nối {connector.connector_number}</legend>
                  <label className="owner-field">
                    Loại đầu nối
                      <select
                        value={customTypes[index] ? 'other' : connector.connector_type ?? ''}
                      disabled={saving}
                        onChange={(event) => {
                          setCustomTypes(items => items.map((item, i) => i === index ? event.target.value === 'other' : item))
                          patch(index, 'connector_type', event.target.value === 'other' ? '' : event.target.value)
                        }}
                      >
                        <option value="">Chưa khai báo</option>
                        {connectorTypes.map(type => <option key={type} value={type}>{type}</option>)}
                        <option value="other">Khác · nhập loại đầu nối</option>
                      </select>
                  </label>
                    {customTypes[index] && <label className="owner-field">Loại đầu nối khác<input maxLength={50} required disabled={saving} value={connector.connector_type ?? ''} onChange={event => patch(index, 'connector_type', event.target.value)} /></label>}
                  <label className="owner-field">
                    Loại dòng điện
                    <select
                      value={connector.current_type ?? ''}
                      disabled={saving}
                      onChange={(event) =>
                        patch(index, 'current_type', event.target.value)
                      }
                    >
                      <option value="">Chưa khai báo</option>
                      <option>AC</option>
                      <option>DC</option>
                    </select>
                  </label>
                  {(
                    [
                      ['max_power_kw', 'Công suất (kW)', '0.001', '99999.999'],
                      ['voltage', 'Điện áp (V)', '0.01', '999999.99'],
                      ['amperage', 'Dòng điện (A)', '0.01', '999999.99'],
                    ] as const
                  ).map(([key, label, precision, maximum]) => (
                    <label className="owner-field" key={key}>
                      {label}
                      <input
                        type="number"
                        min={precision}
                        max={maximum}
                        step={precision}
                        value={connector[key] ?? ''}
                        disabled={saving}
                        onChange={(event) =>
                          patch(index, key, event.target.value)
                        }
                      />
                    </label>
                  ))}
                </fieldset>
              ))}
            </div>
          </>
        ) : (
          <div className="owner-two-column">
            <div>
              <h2>{name || code}</h2>
              <p>
                Mã trụ: {code} · {count} đầu nối
              </p>
              <div className="owner-config-summary">
                {connectors.slice(0, count).map((item) => (
                  <div key={item.connector_number}>
                    <strong>Đầu nối {item.connector_number}</strong>
                    <span>
                      {item.connector_type ?? 'Chưa khai báo loại'} ·{' '}
                      {item.current_type ?? '—'}
                    </span>
                    <span>
                      {item.max_power_kw ?? '—'} kW · {item.voltage ?? '—'} V ·{' '}
                      {item.amperage ?? '—'} A
                    </span>
                  </div>
                ))}
              </div>
              <p>
                {charger
                  ? 'Cập nhật thông số không thay đổi kết nối và phiên sạc.'
                  : 'Trụ mới chưa kết nối. Trạng thái đầu nối sẽ cập nhật khi trụ gửi thông tin.'}
              </p>
            </div>
            <div className="owner-device-preview">
              <ChargerDrawing />
            </div>
          </div>
        )}
      </form>
      <footer className="owner-actions">
        <span>Bước {step + 1} / 3</span>
        <div>
          {step > 0 && (
            <button
              className="secondary-button"
              disabled={saving}
              onClick={() => setStep(step - 1)}
            >
              Quay lại
            </button>
          )}
          <button
            className="primary-button"
            form="owner-charger-form"
            disabled={saving}
          >
            {saving
              ? 'Đang kiểm tra…'
              : step === 2
                ? charger
                  ? 'Lưu thay đổi'
                  : 'Thêm trụ'
                : 'Tiếp tục'}
          </button>
        </div>
      </footer>
    </section>
  )
}
