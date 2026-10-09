
import { useRef, useState, type FormEvent } from 'react'

const MIN_AMOUNT = 10000
const MAX_AMOUNT = 5000000

interface WalletTopUpPageProps {
  onTopUp: (amount: number) => Promise<void>
}

export function WalletTopUpPage({
  onTopUp,
}: WalletTopUpPageProps) {
  const [amount, setAmount] = useState('100000')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const submittingRef = useRef(false)

  const numericAmount = Number(amount)

  const valid =
    /^\d+$/.test(amount) &&
    Number.isSafeInteger(numericAmount) &&
    numericAmount >= MIN_AMOUNT &&
    numericAmount <= MAX_AMOUNT

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!valid || submittingRef.current) return

    submittingRef.current = true
    setLoading(true)
    setError('')

    try {
      await onTopUp(numericAmount)
    } catch {
      setError(
        'Không thể tạo yêu cầu nạp tiền. Vui lòng thử lại.',
      )
    } finally {
      submittingRef.current = false
      setLoading(false)
    }
  }

  return (
    <section className="driver-wallet-page">
      <h2>Nạp tiền vào ví</h2>

      <p>Chọn số tiền muốn nạp vào ví của bạn.</p>

      <form onSubmit={handleSubmit}>
        <label htmlFor="topup-amount">
          Số tiền nạp (VNĐ)
        </label>

        <input
          id="topup-amount"
          type="text"
          inputMode="numeric"
          value={amount}
          disabled={loading}
          onChange={(event) => {
            setAmount(event.target.value)
            setError('')
          }}
          aria-invalid={amount !== '' && !valid}
        />

        {!valid && (
          <p role="alert" className="driver-wallet-error">
            Số tiền phải từ 10.000 đến 5.000.000 VNĐ.
          </p>
        )}

        <div className="driver-wallet-presets">
          {[50000, 100000, 200000, 500000].map((value) => (
            <button
              type="button"
              key={value}
              disabled={loading}
              onClick={() => setAmount(String(value))}
            >
              {value.toLocaleString('vi-VN')}đ
            </button>
          ))}
        </div>

        {error && (
          <p role="alert" className="driver-wallet-error">
            {error}
          </p>
        )}

        <button
          type="submit"
          className="primary-button"
          disabled={!valid || loading}
        >
          {loading ? 'Đang xử lý...' : 'Nạp tiền'}
        </button>
      </form>
    </section>
  )
}
