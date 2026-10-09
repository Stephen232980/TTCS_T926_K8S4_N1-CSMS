import { useEffect, useState } from 'react'

export type TopUpStatus =
  | 'pending'
  | 'success'
  | 'failed'
  | 'cancelled'

export interface TopUpResult {
  status: TopUpStatus
  reason?: string
}

interface WalletTopUpReturnProps {
  transactionId: string
  getStatus: (id: string) => Promise<TopUpResult>
}

const POLL_INTERVAL = 3000
const TIMEOUT = 120000

export function WalletTopUpReturn({
  transactionId,
  getStatus,
}: WalletTopUpReturnProps) {
  const [result, setResult] = useState<TopUpResult>({
    status: 'pending',
  })
  const [error, setError] = useState('')
  const [timedOut, setTimedOut] = useState(false)

  useEffect(() => {
    let active = true
    let busy = false
    let intervalId: ReturnType<typeof setInterval> | undefined
    const startedAt = Date.now()

    async function poll() {
      if (!active || busy) return

      if (Date.now() - startedAt >= TIMEOUT) {
        setTimedOut(true)
        if (intervalId) clearInterval(intervalId)
        return
      }

      busy = true

      try {
        const response = await getStatus(transactionId)

        if (!active) return

        setError('')
        setResult(response)

        if (response.status !== 'pending' && intervalId) {
          clearInterval(intervalId)
        }
      } catch {
        if (active) {
          setError('Không thể kiểm tra trạng thái. Hệ thống sẽ thử lại.')
        }
      } finally {
        busy = false
      }
    }

    void poll()

    intervalId = setInterval(() => {
      void poll()
    }, POLL_INTERVAL)

    return () => {
      active = false
      clearInterval(intervalId)
    }
  }, [transactionId, getStatus])

  return (
    <section className="driver-wallet-page">
      <h2>Trạng thái nạp tiền</h2>

      {result.status === 'pending' && !timedOut && (
        <p role="status">
          Đang chờ hệ thống xác nhận giao dịch...
        </p>
      )}

      {timedOut && result.status === 'pending' && (
        <p role="status">
          Đã hết thời gian chờ tự động.
          Vui lòng kiểm tra lại lịch sử giao dịch.
        </p>
      )}

      {result.status === 'success' && (
        <p role="status">
          Nạp tiền thành công.
        </p>
      )}

      {result.status === 'failed' && (
        <p role="alert">
          Nạp tiền thất bại.
          {result.reason && ` Lý do: ${result.reason}`}
        </p>
      )}

      {result.status === 'cancelled' && (
        <p role="status">
          Giao dịch đã bị huỷ.
          {result.reason && ` Lý do: ${result.reason}`}
        </p>
      )}

      {error && <p role="alert">{error}</p>}
    </section>
  )
}
