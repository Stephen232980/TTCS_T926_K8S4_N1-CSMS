import { useEffect, useRef, useState } from 'react'
import { ownerRequest, jsonBody, OwnerApiError } from '../owner/ownerApi'

type Key = { key: string; value: string | null; readonly: boolean; minimum: number; maximum: number }
type Intent = { id: string; key: string; value: number; actual_value: string | null; state: string; outcome: string | null; reset_requested?: boolean }
type Snapshot = { online: boolean; outcome: string; keys: Key[]; intents: Intent[]; reset_blocked: boolean }
const names: Record<string, string> = { HeartbeatInterval: 'Nhịp tim', MeterValueSampleInterval: 'Chu kỳ số đo' }
const states: Record<string, string> = { queued: 'Đang chờ', sending: 'Đang gửi', accepted: 'Chờ đối chiếu', reboot_required: 'Cần khởi động lại', resetting: 'Đang khởi động lại', verified: 'Đã xác minh', needs_review: 'Cần kiểm tra', failed: 'Không thành công' }
const outcomes: Record<string, string> = { Rejected: 'Trụ từ chối', NotSupported: 'Không hỗ trợ', Timeout: 'Hết thời gian chờ', Disconnected: 'Mất kết nối', Offline: 'Ngoại tuyến', ProtocolError: 'Phản hồi không hợp lệ', ReadbackMismatch: 'Giá trị đọc lại khác', ReadbackUnsupported: 'Không đọc được cấu hình', ChargingBlocked: 'Đang có phiên sạc' }
export function ChargerConfiguration({ chargerId, allowed }: { chargerId: string; allowed: boolean }) {
  const [open, setOpen] = useState(false)
  if (!allowed) return null
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>Cấu hình trụ</summary>{open && <ConfigurationForm key={chargerId} chargerId={chargerId} />}</details>
}
function ConfigurationForm({ chargerId }: { chargerId: string }) {
  const path = `/ops/charge-points/${chargerId}/configuration`
  const [data, setData] = useState<Snapshot | null>(null)
  const [key, setKey] = useState('HeartbeatInterval')
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [readError, setReadError] = useState('')
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [revision, setRevision] = useState(0)
  const [confirmReset, setConfirmReset] = useState(false)
  const [uncertain, setUncertain] = useState<{ url: string; body: object } | null>(null)
  const sending = useRef(false)
  const alive = useRef(true)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false; controller.current?.abort() }
  }, [])
  useEffect(() => {
    const abort = new AbortController()
    let running = false
    async function load(refresh: boolean) {
      if (running) return
      running = true
      if (refresh) { setRefreshing(true); setReadError('') }
      try {
        const next = await ownerRequest<Snapshot>(`${path}?refresh=${refresh}`, { signal: abort.signal })
        if (!abort.signal.aborted) setData(previous => {
          if (refresh || !previous) return { ...next, keys: next.keys.length ? next.keys : previous?.keys ?? [] }
          return { ...next, outcome: next.online ? previous.outcome : next.outcome, keys: previous.keys.map(item => {
            const observed = next.intents.find(intent => intent.key === item.key)
            const before = previous.intents.find(intent => intent.id === observed?.id)
            const changed = observed && (!before || before.state !== observed.state || before.actual_value !== observed.actual_value)
            return changed && observed.actual_value !== null && ['verified', 'needs_review'].includes(observed.state) ? { ...item, value: observed.actual_value } : item
          }) }
        })
      } catch { if (!abort.signal.aborted) { setReadError('Chưa đọc được cấu hình. Hãy tải lại.'); if (refresh) setData(previous => previous ? { ...previous, outcome: 'ReadFailed' } : previous) } }
      finally { running = false; if (refresh && !abort.signal.aborted) setRefreshing(false) }
    }
    void load(true)
    const timer = window.setInterval(() => { if (!document.hidden) void load(false) }, 5000)
    return () => { abort.abort(); window.clearInterval(timer) }
  }, [path, revision])
  async function send(url: string, body: object) {
    if (sending.current) return
    sending.current = true; setBusy(true); setError('')
    setUncertain({ url, body })
    const abort = new AbortController(); controller.current = abort
    try {
      await ownerRequest(url, { ...jsonBody('POST', body), signal: abort.signal })
      setUncertain(null)
      if (alive.current) { setRevision(r => r + 1); setConfirmReset(false) }
    } catch (cause) {
      if (cause instanceof OwnerApiError && cause.status < 500) setUncertain(null)
      if (alive.current) setError(cause instanceof OwnerApiError ? (typeof cause.detail === 'string' ? cause.detail : cause.message) : 'Chưa xác định kết quả. Thử lại cùng yêu cầu hoặc tải lại.')
    }
    finally { sending.current = false; if (alive.current) setBusy(false) }
  }
  const active = data?.intents.find(i => ['queued', 'sending', 'accepted', 'reboot_required', 'resetting'].includes(i.state))
  const selected = data?.keys.find(item => item.key === key)
  const latest = data?.intents[0]
  return <section className="operator-configuration" aria-label="Đổi cấu hình trụ">
    <div className="operator-configuration-values">{data?.keys.map(item => <span key={item.key}>{names[item.key]}: <strong>{item.value ?? '—'}s</strong>{item.readonly ? ' · Chỉ đọc' : ''}</span>)}</div>
    {!data && <p role="status">Đang đọc…</p>}
    {data && !data.online && <p role="status">Trụ ngoại tuyến.</p>}
    {data && data.outcome !== 'Accepted' && data.outcome !== 'Cached' && <p role="status">{outcomes[data.outcome] ?? 'Chưa đọc được giá trị thực.'}</p>}
    <form onSubmit={event => {
      event.preventDefault()
      const number = Number(value)
      if (!selected || !/^\d+$/.test(value) || !Number.isSafeInteger(number) || number < selected.minimum || number > selected.maximum) { setError(`Nhập ${selected?.minimum ?? 30}–${selected?.maximum ?? 600} giây.`); return }
      void send(path, { request_id: crypto.randomUUID(), key, value: number })
    }}>
      <label>Thông số<select value={key} disabled={busy || !!active || !!uncertain} onChange={event => { setKey(event.target.value); setValue('') }}><option value="HeartbeatInterval">Nhịp tim</option><option value="MeterValueSampleInterval">Chu kỳ số đo</option></select></label>
      <label>Giây<input type="number" value={value} min={selected?.minimum} max={selected?.maximum} step="1" disabled={busy || !!active || !!uncertain} onChange={event => setValue(event.target.value)} /></label>
      <button disabled={busy || refreshing || !!active || !!uncertain || !data?.online || !['Accepted', 'Cached'].includes(data.outcome) || !selected || selected.readonly}>Lưu</button>
      <button type="button" disabled={busy || refreshing} onClick={() => setRevision(r => r + 1)}>Đọc lại</button>
    </form>
    {(error || readError) && <p role="alert">{error || readError}</p>}
    {uncertain && !busy && <button onClick={() => { const pending = uncertain; if (pending) void send(pending.url, pending.body) }}>Thử lại cùng yêu cầu</button>}
    {latest && <p role="status">{names[latest.key]} → {latest.value}s · {states[latest.state]}{latest.actual_value !== null ? ` · Đọc lại ${latest.actual_value}s` : ''}{latest.outcome && outcomes[latest.outcome] ? ` · ${outcomes[latest.outcome]}` : ''}</p>}
    {active?.state === 'reboot_required' && !active.reset_requested && <div>
      {data?.reset_blocked ? <p>Đang sạc. Chờ phiên kết thúc để khởi động lại.</p> : confirmReset ? <><p>Khởi động lại mềm trụ này?</p><button disabled={busy || !!uncertain || !data?.online} onClick={() => void send(path + '/reset', { request_id: crypto.randomUUID(), intent_id: active.id, confirm: true })}>Xác nhận</button><button disabled={busy} onClick={() => setConfirmReset(false)}>Hủy</button></> : <button disabled={busy || !!uncertain || !data?.online} onClick={() => setConfirmReset(true)}>Khởi động lại mềm</button>}
    </div>}
    {active?.reset_requested && <p role="status">Đang chờ trụ áp dụng cấu hình.</p>}
  </section>
}
