import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { jsonBody, ownerRequest } from './ownerApi'
import { TariffBandsEditor } from './TariffBandsEditor'
import { normalizedBands, validateBands, type BandValues } from './tariffBands'

interface SubscriptionBand {
  start_min: number
  end_min: number
  energy_rate_vnd_per_kwh: string
  label: string
}

interface SubscriptionPlan {
  id: string
  station_id: string
  station_name: string
  name: string
  monthly_fee_vnd: string
  active: boolean
  bands: SubscriptionBand[]
}

function formatVnd(value: string) {
  return `${new Intl.NumberFormat('vi-VN').format(BigInt(value))} đ`
}

function jsonInteger(raw: string, maximum: bigint, field: string): string {
  const value = raw.trim()
  if (!/^\d+$/.test(value))
    throw new Error(`${field} phải là số nguyên không âm.`)
  const parsed = BigInt(value)
  if (parsed > maximum)
    throw new Error(`${field} vượt giới hạn cho phép.`)
  return parsed.toString()
}

export function StationSubscriptionPlans({ stationId }: { stationId: string }) {
  const [plans, setPlans] = useState<SubscriptionPlan[]>([])
  const [name, setName] = useState('')
  const [monthlyFee, setMonthlyFee] = useState('')
  const [bands, setBands] = useState<BandValues[]>([
    { start: '00:00', end: '24:00', price: '', label: 'Cả ngày' },
  ])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)

  const load = useCallback(async (signal?: AbortSignal) => {
    const rows = await ownerRequest<SubscriptionPlan[]>(
      `/owner/stations/${encodeURIComponent(stationId)}/subscription-plans`,
      { signal },
    )
    setPlans(rows)
  }, [stationId])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal).then(() => setError('')).catch(cause => {
      if (!controller.signal.aborted)
        setError(cause instanceof Error ? cause.message : 'Không tải được gói thuê bao.')
    })
    return () => controller.abort()
  }, [load, revision])

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const fee = jsonInteger(monthlyFee, 9_223_372_036_854_775_807n, 'Phí tháng')
      if (!fee || BigInt(fee) === 0n || !name.trim() || !validateBands(bands).valid)
        throw new Error('Nhập tên gói, phí tháng dương và các khung giá phủ kín 24 giờ.')
      const normalized = normalizedBands(bands)
      const body = `{"name":${JSON.stringify(name.trim())},"monthly_fee_vnd":${fee},"bands":[${normalized.map(band =>
        `{"start_min":${band.start_min},"end_min":${band.end_min},"energy_rate_vnd_per_kwh":${jsonInteger(band.energy_rate_vnd_per_kwh, 9_223_372_036_854_775_807n, 'Đơn giá điện')},"label":${JSON.stringify(band.label ?? '')}}`,
      ).join(',')}]}`
      await ownerRequest<SubscriptionPlan>(
        `/owner/stations/${encodeURIComponent(stationId)}/subscription-plans`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body },
      )
      setName('')
      setMonthlyFee('')
      setBands([{ start: '00:00', end: '24:00', price: '', label: 'Cả ngày' }])
      setRevision(value => value + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không tạo được gói thuê bao.')
    } finally {
      setBusy(false)
    }
  }

  async function deactivate(plan: SubscriptionPlan) {
    if (!window.confirm(`Ngừng bán gói "${plan.name}"? Người đang đăng ký vẫn được gia hạn.`))
      return
    setBusy(true)
    setError('')
    try {
      await ownerRequest<SubscriptionPlan>(
        `/owner/stations/${encodeURIComponent(stationId)}/subscription-plans/${encodeURIComponent(plan.id)}/deactivate`,
        jsonBody('POST', {}),
      )
      setRevision(value => value + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không ngừng bán được gói.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="owner-panel owner-subscription-plans" aria-label="Gói thuê bao tháng">
      <h2>Gói thuê bao tháng</h2>
      <p>Tạo biểu giá điện riêng và phí tháng cho tài xế tại trạm này.</p>
      {error && <p role="alert" className="owner-error">{error}</p>}
      <form onSubmit={event => void create(event)}>
        <label className="owner-field">
          Tên gói
          <input value={name} onChange={event => setName(event.target.value)} maxLength={100} required />
        </label>
        <label className="owner-field">
          Phí tháng (VND)
          <input inputMode="numeric" maxLength={19} value={monthlyFee} onChange={event => setMonthlyFee(event.target.value)} required />
        </label>
        <TariffBandsEditor bands={bands} onChange={setBands} disabled={busy} serverErrors={[]} />
        <p>Khung giá áp dụng theo giờ địa phương của trạm; đơn giá thuê bao thay giá điện thường.</p>
        <button className="primary-button" type="submit" disabled={busy}>Tạo gói</button>
      </form>
      <ul className="owner-subscription-plan-list">
        {plans.map(plan => (
          <li key={plan.id}>
            <div>
              <strong>{plan.name}</strong>
              <span>{formatVnd(plan.monthly_fee_vnd)}/tháng</span>
              {plan.bands.map(band => (
                <small key={`${band.start_min}-${band.end_min}`}>
                  {band.label}: {formatVnd(band.energy_rate_vnd_per_kwh)}/kWh
                </small>
              ))}
              <small>{plan.active ? 'Đang bán' : 'Đã ngừng bán'}</small>
            </div>
            {plan.active && <button className="secondary-button" disabled={busy} onClick={() => void deactivate(plan)}>Ngừng bán</button>}
          </li>
        ))}
      </ul>
      {!plans.length && <p>Trạm chưa có gói thuê bao.</p>}
    </section>
  )
}
