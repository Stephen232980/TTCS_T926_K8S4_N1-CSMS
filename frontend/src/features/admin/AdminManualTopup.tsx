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
  actor_id: string
  request_id: string
  payment_received: boolean
  external_reference: string | null
}
interface Confirmation {
  driver: Account
  amount: number
  externalReference: string
  requestId?: string
}

function restoreRequest(key: string): Confirmation | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null') as Confirmation | null
    return value && typeof value.driver?.id === 'string' && typeof value.driver.email === 'string'
      && Number.isSafeInteger(value.amount) && value.amount > 0
      && typeof value.externalReference === 'string' && value.externalReference.length <= 128
      && typeof value.requestId === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.requestId)
      ? value : null
  } catch { return null }
}

export function AdminManualTopup({ adminId = 'admin' }: { adminId?: string }) {
  const storageKey = `csms:manual-topup:${adminId}`
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [drivers, setDrivers] = useState<Page<Account> | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [refresh, setRefresh] = useState(0)
  const [driver, setDriver] = useState<Account | null>(null)
  const [amount, setAmount] = useState('')
  const [externalReference, setExternalReference] = useState('')
  const [paymentReceived, setPaymentReceived] = useState(() => !!restoreRequest(storageKey))
  const [fields, setFields] = useState<Record<string, string>>({})
  const [confirmation, setConfirmation] = useState<Confirmation | null>(() => restoreRequest(storageKey))
  const [locked, setLocked] = useState(() => !!restoreRequest(storageKey))
  const [conflict, setConflict] = useState(false)
  const requestId = useRef<string | undefined>(restoreRequest(storageKey)?.requestId)
  const active = useRef(true)
  const request = useRef<AbortController | null>(null)
  useEffect(() => { active.current = true; return () => { active.current = false; request.current?.abort() } }, [])
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
    if (externalReference.trim().length > 128)
      next.external_reference = 'Tham chiếu chứng từ tối đa 128 ký tự.'
    setFields(next)
    setError('')
    if (!Object.keys(next).length && driver)
      setConfirmation({ driver, amount: value, externalReference: externalReference.trim(), requestId: requestId.current })
  }

  async function submit() {
    if (!confirmation || !paymentReceived || conflict || sending.current) return
    const frozen = { ...confirmation, requestId: confirmation.requestId ?? requestId.current ?? crypto.randomUUID() }
    try { sessionStorage.setItem(storageKey, JSON.stringify(frozen)) }
    catch { setError('Không lưu được mã yêu cầu để chống nạp trùng. Hãy cho phép lưu dữ liệu phiên rồi thử lại. Chưa gửi khoản nạp.'); return }
    requestId.current = frozen.requestId
    setConfirmation(frozen)
    setLocked(true)
    sending.current = true
    setBusy(true)
    setError('')
    const controller = new AbortController()
    request.current = controller
    const timeout = window.setTimeout(() => controller.abort(), 30000)
    try {
      const data = await adminRequest<TopupResult>(
        `/admin/drivers/${frozen.driver.id}/wallet/manual-topups`,
        { ...writeJson('POST', {
          amount_vnd: frozen.amount,
          request_id: frozen.requestId,
          payment_received: true,
          ...(frozen.externalReference ? { external_reference: frozen.externalReference } : {}),
        }), signal: controller.signal },
      )
      if (!active.current) return
      sessionStorage.removeItem(storageKey)
      setResult({ ...data, email: frozen.driver.email })
      requestId.current = undefined
      setLocked(false)
      setPaymentReceived(false)
      setConfirmation(null)
      setDriver(null)
      setAmount('')
      setExternalReference('')
      setFields({})
    } catch (cause) {
      if (!active.current) return
      if (cause instanceof AdminApiError) {
        const code = cause.code || cause.message
        if (code === 'manual_topup_request_conflict') {
          setConflict(true)
          setError('Mã yêu cầu đã được dùng cho nội dung hoặc quản trị viên khác. Dừng gửi và liên hệ hỗ trợ kèm mã yêu cầu; không tạo mã mới để nạp lại khoản thu này.')
        }
        else if (code === 'wallet_locked')
          setError('Ví tài xế đang bị khóa. Không thể nạp tiền.')
        else if (cause.status === 404)
          setError('Không tìm thấy ví tài xế. Kiểm tra lại tài khoản đã chọn.')
        else if (cause.status === 422) {
          setLocked(false)
          sessionStorage.removeItem(storageKey)
          setFields(
            Object.fromEntries(
              cause.fields.map((field) => [
                field.field,
                field.field === 'amount_vnd'
                  ? 'Số tiền không hợp lệ hoặc vượt hạn mức nạp tay của hệ thống.'
                  : field.field === 'external_reference' ? 'Tham chiếu chứng từ không hợp lệ.' : 'Thông tin xác nhận khoản thu không hợp lệ.',
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
            'Chưa xác định được kết quả nạp. Thử lại cùng khoản thu để kiểm tra; hệ thống giữ nguyên mã yêu cầu và nội dung để tránh cộng tiền hai lần.',
          )
      } else
        setError(
          'Chưa xác định được kết quả nạp. Thử lại cùng khoản thu để kiểm tra; hệ thống giữ nguyên mã yêu cầu và nội dung để tránh cộng tiền hai lần.',
        )
    } finally {
      window.clearTimeout(timeout)
      sending.current = false
      if (active.current) setBusy(false)
    }
  }

  return (
    <>
      <header className="admin-heading">
        <div>
          <h1>Nạp tiền thủ công</h1>
          <p>
            Ghi nhận tiền đã thu vào ví tài xế. Hệ thống tự tạo mã phiếu sau khi xác nhận.
          </p>
        </div>
      </header>
      {result && (
        <section className="admin-panel admin-topup-result" aria-label="Phiếu nạp đã ghi nhận">
        <h2>Nạp tiền đã được ghi nhận</h2>
        <p className="admin-success" role="status">
          Đã nạp {numberText(result.amount_vnd)} VND cho {result.email}. Phiếu
          thu: {result.receipt_code}. Số dư ngay sau khoản nạp này:{' '}
          {numberText(result.balance_after_vnd)} VND. Giao dịch #
          {result.ledger_id} · {dateTime(result.created_at)}.
        </p>
        <dl className="admin-topup-summary"><dt>Người ghi nhận</dt><dd>{result.actor_id}</dd><dt>Thời gian</dt><dd>{dateTime(result.created_at)}</dd><dt>Tham chiếu chứng từ</dt><dd>{result.external_reference || 'Không có'}</dd><dt>Mã yêu cầu</dt><dd>{result.request_id}</dd></dl>
        <p className="admin-muted">Số dư trên phiếu là số dư tại thời điểm ghi nhận khoản nạp, có thể khác số dư ví hiện tại.</p>
        <button className="admin-primary" onClick={() => { setResult(null); setError(''); setConflict(false) }}>Ghi nhận khoản thu mới</button>
        </section>
      )}
      {!result && <section className="admin-panel admin-topup">
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
              Kiểm tra đúng tài xế và số tiền. Chỉ xác nhận khi bạn đã kiểm tra khoản tiền thu bên ngoài. CSMS không tự kiểm chứng tiền đã vào ngân hàng.
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
              <dt>Mã phiếu</dt><dd>Hệ thống tự tạo sau khi ghi nhận</dd>
              <dt>Tham chiếu chứng từ</dt><dd>{confirmation.externalReference || 'Không có'}</dd>
              {confirmation.requestId && <><dt>Mã yêu cầu</dt><dd>{confirmation.requestId}</dd></>}
            </dl>
            {locked && !error && <p className="admin-inline-warning" role="status">Khoản thu này đã được gửi trước đó. Kiểm tra lại bằng cùng mã yêu cầu; không tạo khoản nạp mới cho cùng khoản thu.</p>}
            <label className="admin-topup-received"><input type="checkbox" checked={paymentReceived} disabled={busy || locked} onChange={event => setPaymentReceived(event.target.checked)} /><span>Tôi đã kiểm tra và xác nhận đã thu tiền bên ngoài cho khoản nạp này.</span></label>
            <p className="admin-inline-warning">Không nạp thủ công lại khoản VNPAY đã được cộng vào ví.</p>
            <div className="admin-actions">
              <button disabled={busy || locked} onClick={() => { setConfirmation(null); setPaymentReceived(false) }}>
                Quay lại chỉnh sửa
              </button>
              <button
                className="admin-primary"
                disabled={busy || !paymentReceived || conflict}
                onClick={() => void submit()}
              >
                {busy ? 'Đang nạp tiền…' : locked ? 'Thử lại cùng khoản thu' : 'Xác nhận nạp tiền'}
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
                <label htmlFor="topup-reference">Tham chiếu chứng từ (không bắt buộc)</label>
                <input
                  id="topup-reference"
                  value={externalReference}
                  maxLength={128}
                  aria-invalid={!!fields.external_reference}
                  aria-describedby="topup-reference-help topup-reference-error"
                  onChange={(event) => setExternalReference(event.target.value)}
                />
                <p id="topup-reference-help">
                  Nhập mã chứng từ bên ngoài nếu có. Mã phiếu nạp do CSMS tự tạo; bạn không cần nhập mã phiếu.
                </p>
                <p
                  id="topup-reference-error"
                  className="admin-topup-field-error"
                  role={fields.external_reference ? 'alert' : undefined}
                >
                  {fields.external_reference}
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
      </section>}
    </>
  )
}
