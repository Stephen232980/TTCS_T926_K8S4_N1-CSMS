import { useCallback, useEffect, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import {
  HttpDriverWalletApi,
  type DriverWallet,
  type DriverWalletApi,
  type WalletLedgerItem,
} from './api/driverWalletApi'

const defaultWalletApi = new HttpDriverWalletApi()

function formatVND(amount: number | string): string {
  const num = typeof amount === 'string' ? parseFloat(amount) : amount
  if (isNaN(num)) return '0 ₫'
  return new Intl.NumberFormat('vi-VN', {
    style: 'currency',
    currency: 'VND',
    maximumFractionDigits: 0,
  }).format(num)
}

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
}: {
  walletApi?: DriverWalletApi
}) {
  const [wallet, setWallet] = useState<DriverWallet | null>(null)
  const [transactions, setTransactions] = useState<WalletLedgerItem[]>([])
  const [nextCursor, setNextCursor] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [showTopupModal, setShowTopupModal] = useState(false)

  const loadInitialData = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const [walletData, txData] = await Promise.all([
        walletApi.getWallet(signal),
        walletApi.getTransactions({ limit: 10 }, signal),
      ])
      setWallet(walletData)
      setTransactions(txData.items)
      setNextCursor(txData.next_cursor)
      setHasMore(txData.has_more)
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setError(
        err instanceof Error
          ? err.message
          : 'Không thể tải thông tin ví. Vui lòng thử lại.',
      )
    } finally {
      setLoading(false)
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
    }
  }, [loadInitialData])

  const handleLoadMore = async () => {
    if (!nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      const txData = await walletApi.getTransactions({
        limit: 10,
        cursor: nextCursor,
      })
      setTransactions((prev) => [...prev, ...txData.items])
      setNextCursor(txData.next_cursor)
      setHasMore(txData.has_more)
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : 'Không thể tải thêm giao dịch. Vui lòng thử lại.',
      )
    } finally {
      setLoadingMore(false)
    }
  }

  const balanceNumber = wallet ? Number(wallet.balance) : 0
  const isNegative = wallet?.is_negative || balanceNumber < 0
  const isLowBalance = !isNegative && balanceNumber < 50000

  return (
    <section className="driver-wallet-container" aria-label="Quản lý ví tài xế">
      {/* Header Refresh & Quick Action */}
      <div className="driver-wallet-actions-bar">
        <h2>Ví điện tử CSMS</h2>
        <button
          className="secondary-button driver-wallet-refresh-btn"
          onClick={() => loadInitialData()}
          disabled={loading}
          title="Làm mới dữ liệu"
        >
          <Icon name="session" />
          <span>Làm mới</span>
        </button>
      </div>

      {error && (
        <div className="driver-wallet-alert error" role="alert">
          <p>{error}</p>
          <button className="text-button" onClick={() => loadInitialData()}>
            Thử lại
          </button>
        </div>
      )}

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
                Số dư đang âm {formatVND(wallet?.debt_amount ?? Math.abs(balanceNumber))}.
                Bạn cần nạp thêm tiền để có thể bắt đầu các phiên sạc tiếp theo.
              </p>
            </div>
          </div>
        )}

        {/* Low balance warning */}
        {isLowBalance && (
          <div className="wallet-low-warning" role="status">
            <span className="warning-icon">💡</span>
            <p>
              Số dư hiện tại thấp hơn 50.000 ₫. Vui lòng nạp thêm để đảm bảo đủ
              ngưỡng khởi động phiên sạc.
            </p>
          </div>
        )}

        <div className="driver-balance-cta">
          <button
            className="primary-button topup-button"
            onClick={() => setShowTopupModal(true)}
          >
            <Icon name="plus" />
            <span>Nạp tiền vào ví</span>
          </button>
        </div>
      </div>

      {/* Transaction History Section */}
      <div className="driver-tx-history-section">
        <div className="driver-tx-header">
          <h3>Lịch sử giao dịch</h3>
          <span className="tx-count-hint">Phân trang theo mã dòng</span>
        </div>

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
              onClick={() => setShowTopupModal(true)}
            >
              Nạp tiền ngay
            </button>
          </div>
        ) : (
          <div className="driver-tx-list" role="feed" aria-label="Danh sách giao dịch ví">
            {transactions.map((tx) => {
              const amountNum = Number(tx.amount)
              const isPlus = amountNum > 0
              return (
                <article key={tx.id} className="driver-tx-item">
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
                    {tx.entry_type === 'topup' ||
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
                      <span className="tx-id-badge">Mã dòng #{tx.id}</span>
                      {tx.reference_id && (
                        <span className="tx-ref-badge">
                          Ref: {tx.reference_id}
                        </span>
                      )}
                    </div>
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
              disabled={loadingMore}
            >
              {loadingMore ? 'Đang tải thêm…' : 'Tải thêm giao dịch cũ hơn'}
            </button>
          </div>
        )}
      </div>

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
