import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Icon } from '../../components/icons/Icon'
import {
  HttpDriverWalletApi,
  type DriverWallet,
  type DriverWalletApi,
  type WalletLedgerItem,
} from './api/driverWalletApi'

const defaultWalletApi = new HttpDriverWalletApi()

function moneyValue(value: number | string | bigint): bigint {
  return BigInt(typeof value === 'string' ? value.replace(/\.0+$/, '') : value)
}
function formatVND(amount: number | string | bigint): string {
  try {
    return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND', maximumFractionDigits: 0 }).format(moneyValue(amount))
  } catch { return '—' }
}
interface TransactionDetail extends WalletLedgerItem {
  topup_order_id: string | null
  topup_status: string | null
  topup_reason: string | null
}
const topupStatus: Record<string, string> = {pending: 'Đang chờ', succeeded: 'Thành công', failed: 'Thất bại', cancelled: 'Đã hủy', needs_review: 'Cần xem xét'}

function formatDate(isoString: string): string {
  try {
    const d = new Date(isoString)
    return new Intl.DateTimeFormat('vi-VN', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(d)
  } catch {
    return isoString
  }
}

export function DriverWalletPage({
  walletApi = defaultWalletApi,
  onTopUp,
  onOpenInvoice,
  topUpContent,
}: {
  walletApi?: DriverWalletApi
  onTopUp?: () => void
  onOpenInvoice?: (id: number) => void
  topUpContent?: ReactNode
}) {
  const [wallet, setWallet] = useState<DriverWallet | null>(null)
  const [transactions, setTransactions] = useState<WalletLedgerItem[]>([])
  const [nextCursor, setNextCursor] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  const busy = useRef(false)
  const detailRequest = useRef<AbortController | null>(null)
  const [activeTransaction, setActiveTransaction] = useState<number | null>(null)
  const [sessionDetail, setSessionDetail] = useState<{ id: number; station_name: string; energy_kwh: number | string } | null>(null)
  const [detailError, setDetailError] = useState('')
  const [transactionDetail, setTransactionDetail] = useState<TransactionDetail | null>(null)
  const [showTopupModal, setShowTopupModal] = useState(false)

  const loadInitialData = useCallback(async (signal?: AbortSignal) => {
    if (busy.current) return
    busy.current = true
    const controller = new AbortController()
    request.current = controller
    signal?.addEventListener('abort', () => controller.abort(), { once: true })
    setLoading(true)
    setError('')
    try {
      const [walletData, txData] = await Promise.all([
        walletApi.getWallet(controller.signal),
        walletApi.getTransactions({ limit: 50 }, controller.signal),
      ])
      if (controller.signal.aborted || request.current !== controller) return
      setWallet(walletData)
      setTransactions(txData.items)
      setNextCursor(txData.next_cursor)
      setHasMore(txData.has_more)
    } catch (err: unknown) {
      if (controller.signal.aborted || request.current !== controller) return
      setError(
        err instanceof Error
          ? err.message
          : 'Không thể tải thông tin ví. Vui lòng thử lại.',
      )
    } finally {
      if (request.current === controller) {
        busy.current = false
        if (!controller.signal.aborted) setLoading(false)
      }
    }
  }, [walletApi])

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      void loadInitialData(controller.signal)
    }, 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
      request.current?.abort()
      detailRequest.current?.abort()
      request.current = null
      busy.current = false
    }
  }, [loadInitialData])

  const handleLoadMore = async () => {
    if (nextCursor === null || busy.current) return
    busy.current = true
    const controller = new AbortController()
    request.current = controller
    setError('')
    setLoadingMore(true)
    try {
      const txData = await walletApi.getTransactions({
        limit: 50,
        cursor: nextCursor,
      }, controller.signal)
      if (controller.signal.aborted || request.current !== controller) return
      setTransactions((prev) => [...prev, ...txData.items])
      setNextCursor(txData.next_cursor)
      setHasMore(txData.has_more)
    } catch (err: unknown) {
      if (controller.signal.aborted || request.current !== controller) return
      setError(
        err instanceof Error
          ? err.message
          : 'Không thể tải thêm giao dịch. Vui lòng thử lại.',
      )
    } finally {
      if (request.current === controller) {
        busy.current = false
        if (!controller.signal.aborted) setLoadingMore(false)
      }
    }
  }

  const balanceNumber = wallet ? moneyValue(wallet.balance) : 0n
  const isNegative = wallet?.is_negative || balanceNumber < 0n


  return (
    <section className="driver-wallet-container" aria-label="Quản lý ví tài xế">
      {/* Header Refresh & Quick Action */}
      <div className="driver-wallet-actions-bar">
        <h2>Ví điện tử CSMS</h2>
        <button
          className="secondary-button driver-wallet-refresh-btn"
          onClick={() => loadInitialData()}
          disabled={loading || loadingMore}
          title="Làm mới dữ liệu"
        >
          <Icon name="session" />
          <span>Làm mới</span>
        </button>
      </div>

      {error && (
        <div className="driver-wallet-alert error" role="alert">
          <p>{error}</p>
          <button className="text-button" disabled={loading || loadingMore} onClick={() => loadInitialData()}>
            Thử lại
          </button>
        </div>
      )}

      {loading && !wallet && <p role="status">Đang tải thông tin ví…</p>}
      {!wallet && topUpContent}
      {wallet && <>
      {/* Main Balance Card */}
      <div className={`driver-balance-card ${isNegative ? 'negative' : ''}`}>
        <div className="driver-balance-header">
          <div className="driver-balance-title">
            <Icon name="wallet" />
            <span>Số dư khả dụng</span>
          </div>
          <span className={`wallet-status-badge ${wallet?.status ?? 'active'}`}>
            {wallet?.status === 'active' ? 'Hoạt động' : 'Tạm khóa'}
          </span>
        </div>

        <div className="driver-balance-amount">
          {loading && !wallet ? (
            <span className="balance-placeholder">Đang tải…</span>
          ) : (
            <strong>{formatVND(wallet?.balance ?? 0)}</strong>
          )}
        </div>

        {/* Debt Warning Banner */}
        {isNegative && (
          <div className="wallet-debt-warning" role="alert">
            <span className="warning-icon">⚠️</span>
            <div className="warning-content">
              <strong>Cảnh báo nợ ví</strong>
              <p>
                Số dư đang âm {formatVND(wallet?.debt_amount ?? -balanceNumber)}.
                Bạn cần nạp thêm tiền để có thể bắt đầu các phiên sạc tiếp theo.
              </p>
            </div>
          </div>
        )}

        {!isNegative && <p className="owner-subtle">Ngưỡng bắt đầu sạc phụ thuộc biểu giá của trạm bạn chọn.</p>}

        <div className="driver-balance-cta">
          <button
            className="primary-button topup-button"
            aria-label="Nạp tiền vào ví"
            onClick={() => onTopUp ? onTopUp() : setShowTopupModal(true)}
          >
            <Icon name="plus" />
            <span>Nạp tiền vào ví</span>
          </button>
        </div>
      </div>

      {/* Transaction History Section */}
      {topUpContent}
      <details className="driver-tx-history-section">
        <summary className="driver-tx-header">
          <Icon name="chevronRight" />
          <h3>Lịch sử giao dịch</h3>
          <span>{transactions.length ? `${transactions.length}${hasMore ? '+' : ''} giao dịch` : 'Chưa có giao dịch'}</span>
        </summary>

        {loading && transactions.length === 0 ? (
          <div className="driver-tx-loading" role="status">
            Đang tải lịch sử giao dịch…
          </div>
        ) : transactions.length === 0 ? (
          <div className="driver-tx-empty">
            <Icon name="wallet" />
            <p>Chưa có giao dịch nào được ghi nhận trong ví.</p>
            <button
              className="secondary-button"
              onClick={() => onTopUp ? onTopUp() : setShowTopupModal(true)}
            >
              Nạp tiền ngay
            </button>
          </div>
        ) : (
          <div className="driver-tx-list" role="feed" aria-label="Danh sách giao dịch ví">
            {transactions.map((tx) => {
              const amountNum = moneyValue(tx.amount)
              const isPlus = amountNum > 0n
              return (
                <article key={tx.id} className={`driver-tx-item${tx.entry_type === 'reservation_fee' ? ' reservation-fee-item' : ''}`}>
                  <div
                    className={`tx-type-icon ${
                      tx.entry_type === 'topup' ||
                      tx.entry_type === 'gateway_topup' ||
                      tx.entry_type === 'manual_topup'
                        ? 'topup'
                        : tx.entry_type === 'charge' ||
                            tx.entry_type === 'charging_debit'
                          ? 'charge'
                          : tx.entry_type === 'refund'
                            ? 'refund'
                            : 'adjustment'
                    }`}
                    aria-hidden="true"
                  >
                    {tx.entry_type === 'reservation_fee' ? (
                      <Icon name="wallet" />
                    ) : tx.entry_type === 'topup' ||
                    tx.entry_type === 'gateway_topup' ||
                    tx.entry_type === 'manual_topup' ? (
                      '↑'
                    ) : tx.entry_type === 'charge' ||
                      tx.entry_type === 'charging_debit' ? (
                      '⚡'
                    ) : tx.entry_type === 'refund' ? (
                      '↩'
                    ) : (
                      '⚙'
                    )}
                  </div>
                  <div className="tx-info">
                    <div className="tx-title-row">
                      <strong className="tx-description">{tx.description}</strong>
                      <span
                        className={`tx-amount ${isPlus ? 'plus' : 'minus'}`}
                      >
                        {isPlus ? `+${formatVND(amountNum)}` : formatVND(amountNum)}
                      </span>
                    </div>
                    <div className="tx-sub-row">
                      <span className="tx-date">{formatDate(tx.created_at)}</span>
                      <span className="tx-balance-after">
                        Số dư sau: {formatVND(tx.balance_after)}
                      </span>
                    </div>
                    <div className="tx-meta-row">
                      {tx.reference_id && (
                        <span className="tx-ref-badge">
                          {['charging_session', 'session'].includes(tx.reference_type ?? '') && /^\d+$/.test(tx.reference_id) ? (
                            <button className="text-button" onClick={async () => {
                              setActiveTransaction(tx.id)
                              detailRequest.current?.abort()
                              const controller = new AbortController()
                              detailRequest.current = controller
                              setSessionDetail(null)
                              setTransactionDetail(null)
                              setDetailError('Đang tải phiên sạc…')
                              try {
                                const response = await fetch(`${import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''}/api/v1/driver/charging/sessions/${encodeURIComponent(tx.reference_id!)}`, { credentials: 'include', signal: controller.signal })
                                if (!response.ok) throw new Error('Không thể mở phiên sạc. Vui lòng thử lại.')
                                const data = await response.json()
                                if (controller.signal.aborted) return
                                setSessionDetail(data)
                                setDetailError('')
                              } catch (err) { if (controller.signal.aborted) return; setDetailError(err instanceof Error ? err.message : 'Không thể mở phiên sạc.') }
                            }}>Xem phiên sạc #{tx.reference_id}</button>
                          ) : (
                            <>
                              {tx.entry_type === 'reservation_fee' && tx.reference_type === 'reservation' && /^[0-9a-f-]{36}$/i.test(tx.reference_id) && <a className="text-button" href={`#driver-reservation-${tx.reference_id}`}>Xem đặt chỗ</a>}
                              <details className="tx-reference-value"><summary>Mã giao dịch</summary><p>Mã dòng #{tx.id}</p><p>Mã tham chiếu: {tx.reference_id}</p></details>
                              {['gateway_topup', 'manual_topup'].includes(tx.entry_type) && <button className="text-button" onClick={async () => {
                                setActiveTransaction(tx.id)
                              detailRequest.current?.abort()
                                const controller = new AbortController()
                                detailRequest.current = controller
                                setSessionDetail(null); setTransactionDetail(null); setDetailError('Đang tải giao dịch…')
                                try {
                                  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''}/api/v1/driver/wallet/transactions/${tx.id}`, {credentials: 'include', signal: controller.signal})
                                  if (!response.ok) throw new Error('Không thể mở giao dịch. Vui lòng thử lại.')
                                  const data: TransactionDetail = await response.json()
                                  if (controller.signal.aborted) return
                                  setTransactionDetail(data); setDetailError('')
                                } catch (error) { if (!controller.signal.aborted) setDetailError(error instanceof Error ? error.message : 'Không thể mở giao dịch.') }
                              }}>Xem lần nạp</button>}
                            </>
                          )}
                        </span>
                      )}
                    </div>
                    {activeTransaction === tx.id && <div className="driver-tx-detail">
      {detailError && <p role="status">{detailError}</p>}
      {sessionDetail && <section aria-label="Chi tiết phiên sạc">
        <h3>Phiên sạc #{sessionDetail.id}</h3>
        {onOpenInvoice && <button className="secondary-button" onClick={() => onOpenInvoice(sessionDetail.id)}>Xem hóa đơn phiên này</button>}
        <p>{sessionDetail.station_name} · {sessionDetail.energy_kwh} kWh</p>
        <button className="secondary-button" onClick={() => setSessionDetail(null)}>Đóng chi tiết</button>
      </section>}
      {transactionDetail && <section className="driver-session-summary" aria-label="Chi tiết lần nạp">
        <h3>{transactionDetail.description}</h3>
        <p>Số tiền: {formatVND(transactionDetail.amount)}</p>
        <p>Thời điểm: {formatDate(transactionDetail.created_at)}</p>
        <p>Số dư sau: {formatVND(transactionDetail.balance_after)}</p>
        <p>Mã tham chiếu: {transactionDetail.reference_id}</p>
        {transactionDetail.topup_order_id && <p>Mã đơn: {transactionDetail.topup_order_id}</p>}
        <p>Trạng thái: {transactionDetail.topup_status ? topupStatus[transactionDetail.topup_status] ?? transactionDetail.topup_status : 'Đã ghi nhận vào ví'}</p>
        {transactionDetail.topup_reason && <p>{transactionDetail.topup_reason}</p>}
        <button className="secondary-button" onClick={() => setTransactionDetail(null)}>Đóng chi tiết</button>
      </section>}
                    </div>}
                  </div>
                </article>
              )
            })}
          </div>
        )}

        {hasMore && (
          <div className="driver-load-more-container">
            <button
              className="secondary-button driver-load-more-btn"
              onClick={handleLoadMore}
              disabled={loading || loadingMore}
            >
              {loadingMore ? 'Đang tải thêm…' : 'Tải thêm giao dịch cũ hơn'}
            </button>
          </div>
        )}
      </details>

      </>}
      {/* Topup Info Modal */}
      {showTopupModal && (
        <div
          className="driver-modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="topup-dialog-title"
        >
          <div className="driver-modal-content">
            <div className="driver-modal-header">
              <h3 id="topup-dialog-title">Nạp tiền vào ví tài xế</h3>
              <button
                className="close-button"
                onClick={() => setShowTopupModal(false)}
                aria-label="Đóng"
              >
                <Icon name="close" />
              </button>
            </div>
            <div className="driver-modal-body">
              <p>
                Để nạp tiền vào ví, bạn có thể liên hệ Ban Quản trị tại quầy trạm
                hoặc thanh toán qua cổng nạp giả lập để thử nghiệm.
              </p>
              <div className="topup-guide-card">
                <strong>Thông tin nạp thẻ:</strong>
                <ul>
                  <li>Mã tài xế: {wallet?.driver_id ?? '...'}</li>
                  <li>Loại tiền: {wallet?.currency ?? 'VND'}</li>
                  <li>Trạng thái: {wallet?.status ?? 'active'}</li>
                </ul>
              </div>
              <p className="note-text">
                Tính năng cổng thanh toán tự động (S-35) đang được kết nối trong
                Sprint này.
              </p>
            </div>
            <div className="driver-modal-footer">
              <button
                className="primary-button"
                onClick={() => setShowTopupModal(false)}
              >
                Đã hiểu
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
