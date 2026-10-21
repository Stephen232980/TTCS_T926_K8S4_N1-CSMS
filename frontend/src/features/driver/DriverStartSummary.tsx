import { useEffect, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

export interface DriverStartPricing {
  energy_rate_vnd_per_kwh?: number | null
  idle_rate_vnd_per_minute?: number | null
  grace_minutes?: number | null
}

type WalletState = { kind: 'loading' | 'error' } | { kind: 'ready'; balance: string; status: string; negative: boolean }
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
const money = (value: number) => `${value.toLocaleString('vi-VN')} đ`
const validRate = (value: number | null | undefined): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

export function DriverStartSummary({ pricing }: { pricing?: DriverStartPricing }) {
  const [wallet, setWallet] = useState<WalletState>({ kind: 'loading' })
  useEffect(() => {
    const controller = new AbortController()
    let busy = false
    async function load() {
      if (busy || document.hidden || controller.signal.aborted) return
      busy = true
      setWallet({ kind: 'loading' })
      try {
        const response = await fetch(`${base}/api/v1/driver/wallet`, { credentials: 'include', signal: controller.signal })
        if (response.status === 401) notifySessionUnauthorized()
        if (!response.ok) throw new Error('wallet unavailable')
        const data = await response.json() as { balance?: unknown; currency?: unknown; status?: unknown }
        if (data.currency !== 'VND' || typeof data.status !== 'string' || typeof data.balance !== 'string' && typeof data.balance !== 'number') throw new Error('invalid wallet')
        if (typeof data.balance === 'number' && !Number.isSafeInteger(data.balance)) throw new Error('invalid balance')
        const balance = BigInt(data.balance)
        if (!controller.signal.aborted) setWallet({ kind: 'ready', balance: `${balance.toLocaleString('vi-VN')} đ`, status: data.status, negative: balance < 0n })
      } catch {
        if (!controller.signal.aborted) setWallet({ kind: 'error' })
      } finally { busy = false }
    }
    const timer = window.setTimeout(() => { void load() }, 0)
    const visible = () => { void load() }
    document.addEventListener('visibilitychange', visible)
    return () => { controller.abort(); window.clearTimeout(timer); document.removeEventListener('visibilitychange', visible) }
  }, [])

  return <section className="driver-start-summary" aria-label="Giá và ví trước khi sạc">
    <dl>
      <div><dt>Giá điện</dt><dd>{validRate(pricing?.energy_rate_vnd_per_kwh) ? `${money(pricing.energy_rate_vnd_per_kwh)}/kWh` : 'Chưa có giá'}</dd></div>
      <div><dt>Phí chiếm chỗ</dt><dd>{validRate(pricing?.idle_rate_vnd_per_minute) ? <>{money(pricing.idle_rate_vnd_per_minute)}/phút{validRate(pricing?.grace_minutes) ? <small>Miễn {pricing.grace_minutes} phút</small> : <small>Chưa rõ thời gian miễn phí</small>}</> : 'Chưa có thông tin'}</dd></div>
      <div><dt>Số dư ví</dt><dd aria-live="polite">{wallet.kind === 'ready' ? wallet.balance : wallet.kind === 'loading' ? 'Đang tải…' : 'Chưa tải được'}</dd></div>
    </dl>
    {wallet.kind === 'ready' && wallet.status !== 'active' && <p className="driver-start-wallet-warning">Ví chưa hoạt động. <a href="#driver-wallet">Kiểm tra ví</a></p>}
    {wallet.kind === 'ready' && wallet.status === 'active' && wallet.negative && <p className="driver-start-wallet-warning">Ví đang có số dư âm. <a href="#driver-wallet">Nạp tiền</a></p>}
    {wallet.kind === 'error' && <p>Không tải được số dư. <a href="#driver-wallet">Kiểm tra ví</a></p>}
    <p>Giá lúc chọn trạm. Hệ thống kiểm tra số dư khi bắt đầu sạc.</p>
  </section>
}
