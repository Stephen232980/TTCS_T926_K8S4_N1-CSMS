import { useEffect, useRef, useState } from 'react'
import {
  AdminApiError,
  adminRequest,
  dateTime,
  numberText,
  queryString,
  writeJson,
  type Account,
  type Page,
} from './adminApi'
import { ErrorNotice, Pagination } from './AdminShared'

interface TopupResult {
  ledger_id: number
  amount_vnd: number
  balance_after_vnd: number
  receipt_code: string
  created_at: string
}
interface Confirmation {
  driver: Account
  amount: number
  receipt: string
}

export function AdminManualTopup() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [drivers, setDrivers] = useState<Page<Account> | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [refresh, setRefresh] = useState(0)
  const [driver, setDriver] = useState<Account | null>(null)
  const [amount, setAmount] = useState('')
  const [receipt, setReceipt] = useState('')
  const [fields, setFields] = useState<Record<string, string>>({})
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)
  const [busy, setBusy] = useState(false)
  const sending = useRef(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<
    (TopupResult & { email: string }) | null
  >(null)
  const reviewHeading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setLoading(true)
      setLoadError(null)
      setDrivers(null)
      adminRequest<Page<Account>>(
        `/admin/accounts?${queryString({ role: 'driver', status: 'active', search: search.trim(), page, page_size: 10 })}`,
        { signal: controller.signal },
      )
        .then((data) => {
          if (!controller.signal.aborted) setDrivers(data)
        })
        .catch((cause) => {
          if (!controller.signal.aborted) setLoadError(cause)
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false)
        })
    }, 300)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [search, page, refresh])

  useEffect(() => {
    if (confirmation) reviewHeading.current?.focus()
  }, [confirmation])

  function review() {
    const next: Record<string, string> = {}
    const value = Number(amount)
    if (!driver) next.driver = 'Hãy chọn tài xế cần nạp tiền.'
    if (!/^\d+$/.test(amount) || !Number.isSafeInteger(value) || value <= 0)
      next.amount_vnd = 'Nhập số tiền nguyên dương bằng VND.'
    if (!receipt.trim()) next.receipt_code = 'Vui lòng nhập mã phiếu thu.'
    else if (receipt.trim().length > 128)
      next.receipt_code = 'Mã phiếu thu tối đa 128 ký tự.'
    setFields(next)
    setError('')
    if (!Object.keys(next).length && driver)
      setConfirmation({ driver, amount: value, receipt: receipt.trim() })
  }

  async function submit() {
    if (!confirmation || sending.current) return
    sending.current = true
    setBusy(true)
    setError('')
    try {
      const data = await adminRequest<TopupResult>(
        `/admin/drivers/${confirmation.driver.id}/wallet/manual-topups`,
        writeJson('POST', {
          amount_vnd: confirmation.amount,
          receipt_code: confirmation.receipt,
        }),
      )
      setResult({ ...data, email: confirmation.driver.email })
      setConfirmation(null)
      setDriver(null)
      setAmount('')
      setReceipt('')
      setFields({})
    } catch (cause) {
      if (cause instanceof AdminApiError) {
        const code = cause.code || cause.message
        if (code === 'receipt_already_used')
          setError(
            'Mã phiếu thu đã được sử dụng. Kiểm tra giao dịch đã ghi nhận trước khi tạo khoản nạp khác.',
          )
        else if (code === 'wallet_locked')
          setError('Ví tài xế đang bị khóa. Không thể nạp tiền.')
        else if (cause.status === 404)
          setError('Không tìm thấy ví tài xế. Kiểm tra lại tài khoản đã chọn.')
        else if (cause.status === 422) {
          setFields(
            Object.fromEntries(
              cause.fields.map((field) => [
                field.field,
                field.field === 'amount_vnd'
                  ? 'Số tiền không hợp lệ hoặc vượt hạn mức nạp tay của hệ thống.'
                  : 'Mã phiếu thu không hợp lệ.',
              ]),
            ),
          )
          setError('Dữ liệu chưa hợp lệ. Quay lại để sửa thông tin.')
        } else if (cause.status === 401 || cause.status === 403)
          setError(
            cause.status === 401
              ? 'Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.'
              : cause.message,
          )
        else
          setError(
            'Chưa xác định được kết quả nạp. Kiểm tra giao dịch; nếu thử lại, giữ nguyên mã phiếu thu để tránh nạp trùng.',
          )
      } else
        setError(
          'Chưa xác định được kết quả nạp. Kiểm tra giao dịch; nếu thử lại, giữ nguyên mã phiếu thu để tránh nạp trùng.',
        )
    } finally {
      sending.current = false
      setBusy(false)
    }
  }

  return (
    <>
      <header className="admin-heading">
        <div>
          <h1>Nạp tiền thủ công</h1>
          <p>
            Ghi nhận tiền đã thu vào ví tài xế. Kiểm tra phiếu thu trước khi xác
            nhận.
          </p>
        </div>
      </header>
      {result && (
        <div className="admin-success" role="status">
          Đã nạp {numberText(result.amount_vnd)} VND cho {result.email}. Phiếu
          thu: {result.receipt_code}. Số dư sau nạp:{' '}
          {numberText(result.balance_after_vnd)} VND. Giao dịch #
          {result.ledger_id} · {dateTime(result.created_at)}.
        </div>
      )}
      <section className="admin-panel admin-topup">
        <ol className="admin-steps" aria-label="Các bước nạp tiền">
          <li aria-current={!confirmation ? 'step' : undefined}>
            1. Nhập thông tin
          </li>
          <li aria-current={confirmation ? 'step' : undefined}>
            2. Kiểm tra & xác nhận
          </li>
        </ol>
        {error && <ErrorNotice error={error} />}
        {confirmation ? (
          <div className="admin-wizard">
            <h2 ref={reviewHeading} tabIndex={-1}>
              Xác nhận nạp tiền
            </h2>
            <p>
              Kiểm tra đúng tài xế, số tiền và phiếu thu. Khi xác nhận, số tiền
              sẽ được cộng vào ví.
            </p>
            <dl className="admin-topup-summary">
              <dt>Tài xế</dt>
              <dd>{confirmation.driver.email}</dd>
              <dt>Mã tài xế</dt>
              <dd>{confirmation.driver.id}</dd>
              <dt>Số tiền</dt>
              <dd>
                <strong>{numberText(confirmation.amount)} VND</strong>
              </dd>
              <dt>Mã phiếu thu</dt>
              <dd>{confirmation.receipt}</dd>
            </dl>
            <div className="admin-actions">
              <button disabled={busy} onClick={() => setConfirmation(null)}>
                Quay lại chỉnh sửa
              </button>
              <button
                className="admin-primary"
                disabled={busy}
                onClick={() => void submit()}
              >
                {busy ? 'Đang nạp tiền…' : 'Xác nhận nạp tiền'}
              </button>
            </div>
          </div>
        ) : (
          <form
            className="admin-wizard"
            noValidate
            onSubmit={(event) => {
              event.preventDefault()
              review()
            }}
          >
            <div className="admin-topup-grid">
              <div>
                <label htmlFor="topup-search">Tìm tài xế theo email</label>
                <input
                  id="topup-search"
                  type="search"
              maxLength={320}
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value)
                    setPage(1)
                    setDrivers(null)
                  }}
                />
                <ErrorNotice
                  error={loadError}
                  onRetry={() => setRefresh((value) => value + 1)}
                />
                <div
                  className="admin-topup-drivers"
                  aria-label="Chọn tài xế"
                  aria-busy={loading}
                >
                  {loading && <p role="status">Đang tìm tài xế…</p>}
                  {drivers?.items
                    .filter(
                      (account) =>
                        account.roles.includes('driver') &&
                        account.status === 'active',
                    )
                    .map((account) => (
                      <label key={account.id}>
                        <input
                          type="radio"
                          name="topup-driver"
                          checked={driver?.id === account.id}
                          onChange={() => setDriver(account)}
                        />
                        <span>{account.email}</span>
                      </label>
                    ))}
                  {drivers?.items.length === 0 && (
                    <p>Không tìm thấy tài xế phù hợp.</p>
                  )}
                </div>
                {drivers && (
                  <Pagination
                    page={drivers.page}
                    totalPages={drivers.total_pages}
                    total={drivers.total}
                    busy={loading}
                    onPage={(value) => {
                      setPage(value)
                      setDrivers(null)
                    }}
                  />
                )}
                {driver && (
                  <p className="admin-topup-selected">
                    Đã chọn: <strong>{driver.email}</strong>
                  </p>
                )}
                {fields.driver && (
                  <p className="admin-topup-field-error" role="alert">
                    {fields.driver}
                  </p>
                )}
              </div>
              <div className="admin-topup-fields">
                <label htmlFor="topup-amount">Số tiền (VND)</label>
                <input
                  id="topup-amount"
                  inputMode="numeric"
                  value={amount}
                  aria-invalid={!!fields.amount_vnd}
                  aria-describedby={
                    fields.amount_vnd ? 'topup-amount-error' : undefined
                  }
                  onChange={(event) => setAmount(event.target.value)}
                />
                {fields.amount_vnd && (
                  <p
                    id="topup-amount-error"
                    className="admin-topup-field-error"
                    role="alert"
                  >
                    {fields.amount_vnd}
                  </p>
                )}
                <label htmlFor="topup-receipt">Mã phiếu thu</label>
                <input
                  id="topup-receipt"
                  value={receipt}
                  maxLength={128}
                  aria-invalid={!!fields.receipt_code}
                  aria-describedby="topup-receipt-help topup-receipt-error"
                  onChange={(event) => setReceipt(event.target.value)}
                />
                <p id="topup-receipt-help">
                  Dùng mã trên chứng từ đã thu tiền. Mỗi mã chỉ được ghi nhận
                  một lần.
                </p>
                <p
                  id="topup-receipt-error"
                  className="admin-topup-field-error"
                  role={fields.receipt_code ? 'alert' : undefined}
                >
                  {fields.receipt_code}
                </p>
              </div>
            </div>
            <div className="admin-actions">
              <button className="admin-primary" type="submit">
                Tiếp tục kiểm tra
              </button>
            </div>
          </form>
        )}
      </section>
    </>
  )
}
