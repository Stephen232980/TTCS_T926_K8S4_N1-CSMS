import { useCallback, useEffect, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

interface PlanBand {
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
  bands: PlanBand[]
}

interface DriverSubscription {
  id: string
  station_id: string
  station_name: string
  plan_id: string
  plan_name: string
  monthly_fee_vnd: string
  status: 'active' | 'past_due' | 'cancelled'
  current_period_start: string
  current_period_end: string
  next_billing_at: string | null
}

const apiBase = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
const vnd = (value: string) => `${new Intl.NumberFormat('vi-VN').format(BigInt(value))} đ`
const time = (value: string) => new Intl.DateTimeFormat('vi-VN', {
  dateStyle: 'medium',
  timeZone: 'Asia/Ho_Chi_Minh',
}).format(new Date(value))

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1/driver/subscriptions${path}`, {
    credentials: 'include',
    headers: { Accept: 'application/json', ...init?.headers },
    ...init,
  })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) {
    if (response.status === 402) throw new Error('Ví không đủ tiền để thanh toán phí tháng. Nạp tiền rồi thử lại.')
    if (response.status === 409) throw new Error('Đã có gói đang hiệu lực tại trạm này hoặc ví đang khóa.')
    if (response.status === 401) throw new Error('Phiên đăng nhập đã hết hạn.')
    const body = await response.json().catch(() => ({})) as { detail?: unknown }
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Không xử lý được gói thuê bao.')
  }
  return response.json() as Promise<T>
}

export function DriverSubscriptions({ onTopUp }: { onTopUp: () => void }) {
  const [plans, setPlans] = useState<SubscriptionPlan[]>([])
  const [subscriptions, setSubscriptions] = useState<DriverSubscription[]>([])
  const [error, setError] = useState('')
  const [busyPlan, setBusyPlan] = useState('')
  const [revision, setRevision] = useState(0)

  const load = useCallback(async (signal?: AbortSignal) => {
    const [available, current] = await Promise.all([
      request<SubscriptionPlan[]>('/plans', { signal }),
      request<DriverSubscription[]>('', { signal }),
    ])
    setPlans(available)
    setSubscriptions(current)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal).then(() => setError('')).catch(cause => {
      if (!controller.signal.aborted)
        setError(cause instanceof Error ? cause.message : 'Không tải được gói thuê bao.')
    })
    return () => controller.abort()
  }, [load, revision])

  async function subscribe(plan: SubscriptionPlan) {
    if (!window.confirm(`Thanh toán ${vnd(plan.monthly_fee_vnd)} ngay và tự động gia hạn mỗi tháng cho gói "${plan.name}" tại ${plan.station_name}?`))
      return
    setBusyPlan(plan.id)
    setError('')
    try {
      await request<DriverSubscription>(`/plans/${encodeURIComponent(plan.id)}`, { method: 'POST' })
      setRevision(value => value + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không đăng ký được gói.')
    } finally {
      setBusyPlan('')
    }
  }

  async function cancel(subscription: DriverSubscription) {
    if (!window.confirm(`Hủy gia hạn gói "${subscription.plan_name}"? Quyền lợi vẫn dùng được đến ${time(subscription.current_period_end)}.`))
      return
    setBusyPlan(subscription.id)
    setError('')
    try {
      await request<DriverSubscription>(`/${encodeURIComponent(subscription.id)}`, { method: 'DELETE' })
      setRevision(value => value + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không hủy được gia hạn.')
    } finally {
      setBusyPlan('')
    }
  }

  const subscribedStations = new Set(subscriptions
    .filter(item => item.status !== 'cancelled' || Date.parse(item.current_period_end) > Date.now())
    .map(item => item.station_id))

  return (
    <section className="driver-subscriptions" aria-label="Gói thuê bao tháng">
      <header>
        <h2>Gói thuê bao tháng</h2>
        <p>Phí được thu từ ví ngay khi đăng ký. Gói tự gia hạn mỗi tháng; hủy trước kỳ tiếp theo để dừng thu phí.</p>
      </header>
      {error && <p className="driver-subscription-error" role="alert">{error}</p>}
      {subscriptions.length > 0 && <section aria-label="Gói đang sử dụng">
        <h3>Gói của bạn</h3>
        <ul>
          {subscriptions.map(subscription => (
            <li key={subscription.id}>
              <div>
                <strong>{subscription.plan_name} · {subscription.station_name}</strong>
                <span>{vnd(subscription.monthly_fee_vnd)}/tháng</span>
                <span>{subscription.status === 'past_due' ? 'Chờ thanh toán gia hạn' : subscription.status === 'cancelled' ? 'Đã hủy gia hạn' : 'Đang hoạt động'}</span>
                <small>Đã thanh toán đến {time(subscription.current_period_end)}</small>
                {subscription.status === 'past_due' && <button className="secondary-button" onClick={onTopUp}>Nạp tiền vào ví</button>}
              </div>
              {subscription.status !== 'cancelled' && <button className="secondary-button" disabled={busyPlan === subscription.id} onClick={() => void cancel(subscription)}>Hủy gia hạn</button>}
            </li>
          ))}
        </ul>
      </section>}
      <section aria-label="Gói đang bán">
        <h3>Gói đang bán</h3>
        {!plans.length && <p>Hiện chưa có gói nào được mở bán.</p>}
        <ul>
          {plans.map(plan => (
            <li key={plan.id}>
              <div>
                <strong>{plan.name} · {plan.station_name}</strong>
                <span>{vnd(plan.monthly_fee_vnd)}/tháng</span>
                {plan.bands.map(band => <small key={`${band.start_min}-${band.end_min}`}>{band.label}: {vnd(band.energy_rate_vnd_per_kwh)}/kWh</small>)}
              </div>
              <button className="primary-button" disabled={busyPlan === plan.id || subscribedStations.has(plan.station_id)} onClick={() => void subscribe(plan)}>
                {subscribedStations.has(plan.station_id) ? 'Đã có gói tại trạm' : 'Đăng ký'}
              </button>
            </li>
          ))}
        </ul>
      </section>
    </section>
  )
}
