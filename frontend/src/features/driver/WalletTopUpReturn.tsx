import { useEffect, useState } from 'react'
import { WalletTopUpApiError, type TopUpResult } from './walletTopUpApi'

export type { TopUpStatus, TopUpResult } from './walletTopUpApi'

interface WalletTopUpReturnProps {
  transactionId: string
  getStatus: (id: string, signal?: AbortSignal) => Promise<TopUpResult>
  onSucceeded?: () => Promise<void> | void
  onBack?: () => void
}

const POLL_INTERVAL = 3000
const TIMEOUT = 120000

interface Snapshot {
  id: string
  result: TopUpResult
  error: string
  timedOut: boolean
  loadingWallet: boolean
}

export function WalletTopUpReturn({ transactionId, getStatus, onSucceeded, onBack }: WalletTopUpReturnProps) {
  const [retry, setRetry] = useState(0)
  const [snapshot, setSnapshot] = useState<Snapshot>(() => ({
    id: transactionId, result: { status: 'pending' }, error: '', timedOut: false, loadingWallet: false,
  }))

  useEffect(() => {
    const reset: Snapshot = { id: transactionId, result: { status: 'pending' }, error: '', timedOut: false, loadingWallet: false }
    if (!transactionId.trim()) return

    let active = true
    let busy = false
    const controller = new AbortController()
    const update = (change: Partial<Snapshot>) => {
      if (active) setSnapshot(previous => ({ ...(previous.id === transactionId ? previous : reset), ...change, id: transactionId }))
    }
    const stop = () => {
      clearInterval(intervalId)
      clearTimeout(timeoutId)
    }

    async function poll() {
      if (!active || busy) return
      busy = true
      try {
        const response = await getStatus(transactionId, controller.signal)
        if (!active) return
        update({ result: response, error: '' })
        if (response.status !== 'pending') {
          stop()
          if (response.status === 'succeeded' && onSucceeded) {
            update({ loadingWallet: true })
            try { await onSucceeded() }
            catch { update({ error: 'Đã xác nhận thanh toán, nhưng chưa tải lại được dữ liệu ví. Vui lòng mở lại Ví của tôi.' }) }
            finally { update({ loadingWallet: false }) }
          }
        }
      } catch (cause) {
        if (active && !controller.signal.aborted) {
          const message = cause instanceof WalletTopUpApiError ? cause.message : 'Không thể kiểm tra trạng thái. Hệ thống sẽ thử lại.'
          update({ error: message })
          // Invalid order or expired login should not keep polling.
          if (cause instanceof WalletTopUpApiError && ['not_found', 'auth'].includes(cause.kind)) stop()
        }
      } finally { busy = false }
    }

    // Independent deadline: even a getStatus promise that never settles times out.
    const intervalId = setInterval(() => { void poll() }, POLL_INTERVAL)
    const timeoutId = setTimeout(() => {
      if (!active) return
      active = false
      stop()
      controller.abort()
      setSnapshot(previous => ({ ...(previous.id === transactionId ? previous : reset), id: transactionId, timedOut: true }))
    }, TIMEOUT)
    void poll()
    return () => { active = false; stop(); controller.abort() }
  }, [transactionId, getStatus, onSucceeded, retry])

  const current: Snapshot = snapshot.id === transactionId ? snapshot : {
    id: transactionId, result: { status: 'pending' as const }, error: '', timedOut: false, loadingWallet: false,
  }
  const { result, error, timedOut, loadingWallet } = current
  const retryStatus = () => {
    setSnapshot({ id: transactionId, result: { status: 'pending' }, error: '', timedOut: false, loadingWallet: false })
    setRetry(value => value + 1)
  }

  return <section className="driver-wallet-page" aria-label="Trạng thái nạp tiền">
    <h2>Trạng thái nạp tiền</h2>
    {transactionId ? <p>Mã đơn: <strong>{transactionId}</strong></p> : <p role="alert">URL quay về thiếu mã đơn order_code. Không thể xác minh thanh toán.</p>}
    {transactionId && result.status === 'pending' && !timedOut && <p role="status">Đang chờ hệ thống xác nhận giao dịch...</p>}
    {transactionId && timedOut && result.status === 'pending' && <p role="status">Đã hết thời gian chờ tự động (2 phút). Giao dịch chưa được xác nhận, vui lòng kiểm tra lại.</p>}
    {result.status === 'succeeded' && <p role="status">Backend đã xác nhận nạp tiền thành công.{loadingWallet && ' Đang tải lại thông tin ví...'}</p>}
    {result.status === 'failed' && <p role="alert">Nạp tiền thất bại.{result.reason && ` Lý do: ${result.reason}`}</p>}
    {result.status === 'cancelled' && <p role="status">Giao dịch đã bị huỷ.{result.reason && ` Lý do: ${result.reason}`}</p>}
    {result.status === 'needs_review' && <p role="status">Giao dịch đang cần kiểm tra thủ công. Chưa thể xác nhận tiền đã vào ví.{result.reason && ` Chi tiết: ${result.reason}`}</p>}
    {error && <p role="alert" className="driver-wallet-error">{error}</p>}
    {transactionId && (timedOut || (error && result.status === 'pending')) && <button type="button" className="secondary-button" onClick={retryStatus}>Kiểm tra lại trạng thái đơn</button>}
    {onBack && <button type="button" className="secondary-button" onClick={onBack}>Về Ví của tôi</button>}
  </section>
}
