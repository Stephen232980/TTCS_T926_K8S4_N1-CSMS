import { useEffect, useState } from 'react'
import { driverInvoiceApi, invoiceMoney, type DriverInvoice, type DriverInvoiceApi, type InvoiceList, type InvoiceStatus } from './driverInvoiceApi'

const statusText: Record<InvoiceStatus, string> = {
  ready: 'Đã lập hóa đơn', pending: 'Đang chờ lập hóa đơn',
  needs_review: 'Phiên đang chờ xử lý', in_progress: 'Phiên sạc chưa kết thúc',
  awaiting_unplug: 'Đã dừng sạc, đang chờ xác nhận rút súng',
}
const vietnamTime = (value: string) => new Intl.DateTimeFormat('vi-VN', {
  dateStyle: 'short', timeStyle: 'short', timeZone: 'Asia/Ho_Chi_Minh',
}).format(new Date(value))
const localDate = (value: string) => value.split('-').reverse().join('/')
const lineTotal = (invoice: DriverInvoice, type: 'energy' | 'idle') => invoiceMoney(
  invoice.lines.filter(line => line.line_type === type).reduce((total, line) => total + BigInt(line.amount_vnd), 0n).toString(),
)

export function DriverInvoicePage({ api = driverInvoiceApi, sessionId, onOpen, onBack }: {
  api?: DriverInvoiceApi
  sessionId?: number
  onOpen: (id: number) => void
  onBack: () => void
}) {
  const [page, setPage] = useState<InvoiceList>()
  const [invoice, setInvoice] = useState<DriverInvoice>()
  const [cursor, setCursor] = useState<number>()
  const [retry, setRetry] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    async function load() {
      setLoading(true)
      setError('')
      setInvoice(undefined)
      try {
        if (sessionId !== undefined) {
          const data = await api.get(sessionId, controller.signal)
          if (active) setInvoice(data)
        } else {
          const data = await api.list(cursor, controller.signal)
          if (active) setPage(data)
        }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : 'Không tải được hóa đơn. Vui lòng thử lại.')
      } finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false; controller.abort() }
  }, [api, sessionId, cursor, retry])

  return <section className="driver-wallet-page driver-invoice" aria-label="Hóa đơn phiên sạc">
    <h2>{sessionId !== undefined ? `Hóa đơn phiên #${sessionId}` : 'Hóa đơn phiên sạc'}</h2>
    {sessionId !== undefined && <button className="secondary-button" onClick={onBack}>Về danh sách hóa đơn</button>}
    {loading && <p role="status">Đang tải hóa đơn…</p>}
    {error && <p role="alert">{error}</p>}
    {!loading && (error || invoice?.status === 'pending' || invoice?.status === 'needs_review' || invoice?.status === 'awaiting_unplug') &&
      <button className="secondary-button" onClick={() => setRetry(value => value + 1)}>Kiểm tra lại</button>}
    {!loading && !error && sessionId === undefined && page && <>
      <p>Hóa đơn được chốt sau khi dừng sạc và xác nhận rút súng. Chọn một phiên để xem cách tính tiền.</p>
      {!page.items.length && <p>Chưa có phiên đã kết thúc để xem hóa đơn.</p>}
      <ul className="driver-invoice-list">{page.items.map(item => <li key={item.session_id}>
        <button className="secondary-button" onClick={() => onOpen(item.session_id)}>
          <strong>Phiên #{item.session_id} · {item.station_name}</strong>
          <span>{statusText[item.status]}{item.status === 'ready' && item.total_vnd !== null ? ` · ${invoiceMoney(item.total_vnd)}` : ''}</span>
        </button>
      </li>)}</ul>
      {page.next_cursor !== null && <button className="secondary-button" onClick={() => setCursor(page.next_cursor!)}>Xem các phiên cũ hơn</button>}
      {cursor !== undefined && <button className="secondary-button" onClick={() => setCursor(undefined)}>Về các phiên mới nhất</button>}
    </>}
    {!loading && !error && invoice && <>
      <p>{invoice.station_name}</p>
      {invoice.status !== 'ready' ? <p role="status">{statusText[invoice.status]}. Hóa đơn chưa sẵn sàng; chưa có số tiền được xác nhận để hiển thị.</p> : <>
        <div className="driver-invoice-summary">
          <p className="driver-invoice-total">Tổng cộng: <strong>{invoiceMoney(invoice.total_vnd!)}</strong></p>
          <dl><dt>Tiền điện</dt><dd>{lineTotal(invoice, 'energy')}</dd><dt>Phí chiếm trụ</dt><dd>{lineTotal(invoice, 'idle')}</dd></dl>
        </div>
        <p>Thời gian hiển thị theo giờ Việt Nam (UTC+7). Ngày tính giá theo giờ trạm được lưu trên hóa đơn.</p>
        <ol className="driver-invoice-lines">{invoice.lines.map(line => <li key={line.id}>
          <h3>{line.line_type === 'idle' ? 'Phí chiếm trụ' : 'Tiền điện'} · {line.band_label}</h3>
          <p>Ngày tính giá: {localDate(line.local_date)}</p>
          <p>{vietnamTime(line.started_at)} – {vietnamTime(line.ended_at)}</p>
          <dl>
            {line.line_type === 'energy' && <><dt>Điện năng</dt><dd>{line.energy_kwh.replace('.', ',')} kWh</dd></>}
            <dt>Đơn giá</dt><dd>{invoiceMoney(line.rate_vnd)}{line.line_type === 'energy' ? '/kWh' : '/phút'}</dd>
            <dt>Thành tiền</dt><dd>{invoiceMoney(line.amount_vnd)}</dd>
          </dl>
        </li>)}</ol>
        <details className="driver-invoice-technical"><summary>Thông tin đối chiếu</summary>
          <p>Mã hóa đơn: <strong>{invoice.invoice_id}</strong></p>
          <p>Quy tắc làm tròn: {invoice.rounding_rule}</p>
          {invoice.lines.map(line => <div key={line.id}><p>{line.line_type === 'idle' ? 'Phí chiếm trụ' : 'Tiền điện'} · {line.band_label}: Phiên bản biểu giá {line.tariff_id}</p>{line.interpolated && <p>Số đo tại ranh giới được nội suy.</p>}</div>)}
          <p>Hóa đơn được đọc từ bản ghi đã lưu; thay đổi biểu giá sau phiên không tính lại hóa đơn này.</p>
        </details>
      </>}
    </>}
  </section>
}
