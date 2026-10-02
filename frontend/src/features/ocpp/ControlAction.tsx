import { useEffect, useRef, useState } from 'react'
import { controlRequest, controlStatuses } from './controlApi'
interface Result { id: string; status: string }

export function ControlAction({ chargerId, sessionId, label, onDone }: { chargerId?: string; sessionId?: number; label: string; onDone?: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [resetType, setResetType] = useState('Soft')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [issued, setIssued] = useState(false)
  const requestId = useRef('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const isReset = !!chargerId
  async function submit() {
    setBusy(true); setError(''); setIssued(true)
    controller.current = new AbortController()
    const signal = controller.current.signal
    requestId.current ||= crypto.randomUUID()
    try {
      let result = await controlRequest<Result>(isReset ? `/charge-points/${chargerId}/reset` : `/sessions/${sessionId}/stop`, { method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: requestId.current, ...(isReset ? { type: resetType } : {}) }) })
      setStatus(result.status)
      while (result.status === 'Pending' && !signal.aborted) {
        await new Promise<void>(resolve => { const timer = window.setTimeout(resolve, 1000); signal.addEventListener('abort', () => { window.clearTimeout(timer); resolve() }, { once: true }) })
        if (signal.aborted) return
        result = await controlRequest<Result>(`/commands/${requestId.current}`, { signal })
        setStatus(result.status)
      }
      if (!signal.aborted) onDone?.()
    } catch (err) {
      if (!signal.aborted) setError(err instanceof Error ? err.message : 'Không gửi được lệnh.')
    } finally { if (!signal.aborted) setBusy(false) }
  }
  return <div className="remote-control">
    <button className="secondary-button" aria-expanded={expanded} onClick={() => { setExpanded(!expanded); requestId.current = ''; setIssued(false); setStatus(''); setError(''); setResetType('Soft') }} disabled={busy}>{isReset ? 'Khởi động lại' : 'Dừng từ xa'} {label}</button>
    {expanded && <section className="remote-control__confirmation" aria-label={`Xác nhận điều khiển ${label}`}>
      <h3>{isReset ? 'Khởi động lại trụ' : 'Dừng phiên tại trụ'} {label}</h3>
      <p>{isReset ? 'Trụ có thể ngắt kết nối và gián đoạn phiên đang sạc khi khởi động lại.' : 'Trụ nhận lệnh chưa có nghĩa là phiên đã kết thúc. Hệ thống chờ tin kết thúc thật, tối đa 2 phút trước khi yêu cầu kiểm tra.'}</p>
      {isReset && <label>Kiểu khởi động<select value={resetType} disabled={busy || issued} onChange={event => setResetType(event.target.value)}><option value="Soft">Khởi động mềm</option><option value="Hard">Khởi động cứng — có thể ngắt sạc ngay</option></select></label>}
      <div className="remote-control__buttons"><button className="primary-button" onClick={() => void submit()} disabled={busy || (!!status && status !== 'Pending')}>{busy ? 'Đang chờ trụ…' : error ? 'Kiểm tra lại yêu cầu' : 'Xác nhận gửi lệnh'}</button><button className="secondary-button" disabled={busy} onClick={() => setExpanded(false)}>Đóng</button></div>
      {status && <p role={status === 'Accepted' || status === 'Pending' ? 'status' : 'alert'}>{controlStatuses[status] ?? status}{status === 'Accepted' && !isReset && ' Phiên vẫn mở cho đến khi trụ gửi tin kết thúc.'}</p>}
      {error && <p role="alert">{error}</p>}
    </section>}
  </div>
}
