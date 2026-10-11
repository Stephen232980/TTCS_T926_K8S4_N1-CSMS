import { useRef, useState, type FormEvent } from 'react'
import { WalletTopUpApiError, type TopUpCreated } from './walletTopUpApi'

const MIN_AMOUNT = 10000
const MAX_AMOUNT = 5000000
const PRESETS = [50000, 100000, 200000, 500000]

interface WalletTopUpPageProps {
  storageKey?: string
  onOrder?: (id: string) => void
  onTopUp: (amount: number) => Promise<TopUpCreated>
  onCheckOrder?: (id: string) => void
  onRedirect?: (url: string) => void
}

export function WalletTopUpPage({ storageKey, onOrder, onTopUp, onCheckOrder, onRedirect = url => window.location.assign(url) }: WalletTopUpPageProps) {
  const [amount, setAmount] = useState('100000')
  const [loading, setLoading] = useState(false)
  const [redirecting, setRedirecting] = useState(false)
  const [error, setError] = useState('')
  const [pendingOrder, setPendingOrder] = useState(() => storageKey ? sessionStorage.getItem(storageKey) ?? '' : '')
  const [uncertain, setUncertain] = useState(() => Boolean(storageKey && sessionStorage.getItem(storageKey) !== null))
  const submittingRef = useRef(false)
  const numericAmount = Number(amount)
  const valid = /^\d+$/.test(amount) && Number.isSafeInteger(numericAmount) &&
    numericAmount >= MIN_AMOUNT && numericAmount <= MAX_AMOUNT
  const locked = loading || redirecting || uncertain

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!valid || submittingRef.current || locked) return
    if (storageKey && sessionStorage.getItem(storageKey) !== null) return
    if (storageKey) sessionStorage.setItem(storageKey, '')
    onOrder?.('')
    submittingRef.current = true
    setLoading(true)
    setError('')
    let createdOrder = ''
    try {
      const created = await onTopUp(numericAmount)
      createdOrder = created.order_id
      if (storageKey) sessionStorage.setItem(storageKey, createdOrder)
      onOrder?.(createdOrder)
      if (!created.redirect_url || !created.order_id) throw new WalletTopUpApiError(
        'uncertain', 'Backend không trả về đầy đủ thông tin thanh toán.', undefined, created.order_id,
      )
      setRedirecting(true)
      onRedirect(created.redirect_url)
    } catch (cause) {
      // Khi điều hướng gateway thất bại, thoát trạng thái "đang chuyển".
      // Vẫn giữ khóa POST nhờ uncertain để tránh tạo trùng lệnh nạp.
      setRedirecting(false)
      if (cause instanceof WalletTopUpApiError) {
        setError(cause.message)
        if (cause.orderId) {
          setPendingOrder(cause.orderId)
          if (storageKey) sessionStorage.setItem(storageKey, cause.orderId)
          onOrder?.(cause.orderId)
        }
        if (!cause.orderId && !['uncertain', 'gateway'].includes(cause.kind) && storageKey) sessionStorage.removeItem(storageKey)
        if (cause.orderId || cause.kind === 'uncertain' || cause.kind === 'gateway') setUncertain(true)
      } else {
        setError('Không chuyển được tới cổng thanh toán hoặc chưa rõ kết quả tạo lệnh. Không gửi lại trước khi kiểm tra.')
        if (createdOrder) setPendingOrder(createdOrder)
        setUncertain(true)
      }
    } finally {
      submittingRef.current = false
      setLoading(false)
    }
  }

  return <section className="driver-wallet-page">
    <h2>Nạp tiền vào ví</h2>
    <p>Chọn số tiền muốn nạp. Số dư chỉ thay đổi sau khi backend xác nhận thanh toán.</p>
    <form onSubmit={event => void handleSubmit(event)} noValidate>
      <label htmlFor="topup-amount">Số tiền nạp (VNĐ)</label>
      <input id="topup-amount" type="text" inputMode="numeric" value={amount}
        disabled={locked} aria-invalid={!valid} aria-describedby={!valid ? 'topup-validation' : error ? 'topup-error' : undefined}
        onChange={event => { setAmount(event.target.value); setError('') }} />
      {!valid && <p id="topup-validation" role="alert" className="driver-wallet-error">Số tiền phải từ 10.000 đến 5.000.000 VNĐ.</p>}
      <div className="driver-wallet-presets" aria-label="Mức nạp nhanh">
        {PRESETS.map(value => <button className="driver-wallet-preset" type="button" key={value}
          aria-pressed={numericAmount === value && valid} disabled={locked}
          onClick={() => { setAmount(String(value)); setError('') }}>
          {value.toLocaleString('vi-VN')}đ
        </button>)}
      </div>
      {error && <p id="topup-error" role="alert" className="driver-wallet-error">{error}</p>}
      {pendingOrder && <p role="status">Mã đơn đã ghi nhận: <strong>{pendingOrder}</strong></p>}
      {pendingOrder && onCheckOrder && <button className="secondary-button" type="button" onClick={() => onCheckOrder(pendingOrder)}>
        Kiểm tra trạng thái đơn này
      </button>}
      {uncertain && !pendingOrder && <p role="status">Chưa có mã đơn để tra cứu. Vui lòng kiểm tra lịch sử giao dịch hoặc liên hệ hỗ trợ trước khi tạo lệnh khác.</p>}
      <button type="submit" className="primary-button" disabled={!valid || locked}>
        {redirecting ? 'Đang chuyển tới cổng thanh toán...' : loading ? 'Đang tạo lệnh...' : 'Nạp tiền'}
      </button>
    </form>
  </section>
}
