import { useEffect, useRef, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

export interface ControlledSession {
  id: number
  ended_at?: string | null
  demo_unplug_available?: boolean
}
interface Command { id: string; status: string }
const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
const labels: Record<string, string> = {
  Pending: 'Đang chờ trụ trả lời. Chưa xác nhận phiên đã dừng.',
  Accepted: 'Trụ đã nhận yêu cầu. Đang chờ tín hiệu thực tế từ trụ.',
  Rejected: 'Trụ từ chối yêu cầu. Hãy kiểm tra thiết bị hoặc liên hệ vận hành.',
  Offline: 'Trụ đang ngoại tuyến. Chưa thể xác nhận thao tác.',
  Timeout: 'Trụ chưa trả lời đúng hạn. Kiểm tra trạng thái tại trụ trước khi thao tác tiếp.',
  Disconnected: 'Trụ mất kết nối khi xử lý. Chưa xác nhận thao tác hoàn tất.',
  ProtocolError: 'Phản hồi từ trụ không hợp lệ. Vui lòng liên hệ vận hành.',
}

async function read(response: Response): Promise<Command> {
    if (response.status === 401) notifySessionUnauthorized()
    if (!response.ok) throw new Error(response.status === 403
      ? 'Bạn không có quyền thao tác phiên này.'
      : response.status === 409
        ? 'Trạng thái phiên đã thay đổi. Kiểm tra lại trước khi thao tác.'
        : 'Chưa xác nhận được kết quả. Kiểm tra lại với cùng mã yêu cầu.')
    return response.json() as Promise<Command>
  }


export function DriverSessionControls({ session, onRefresh }: {
  session: ControlledSession
  onRefresh: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [unplugged, setUnplugged] = useState(false)
  const [command, setCommand] = useState<Command | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const sending = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const submittedAction = useRef<'stop' | 'demo-unplug' | null>(null)
  const refresh = useRef(onRefresh)
  useEffect(() => { refresh.current = onRefresh }, [onRefresh])
  const [uncertainAction, setUncertainAction] = useState<'stop' | 'demo-unplug' | null>(null)

  useEffect(() => {
    return () => controller.current?.abort()
  }, [session.id])


  async function send(action: 'stop' | 'demo-unplug') {
    if (sending.current) return
    sending.current = true; submittedAction.current = action; setBusy(true); setError('')
    const abort = new AbortController()
    controller.current?.abort(); controller.current = abort
    const storageKey = `csms:session-command:${session.id}:${action}`
    try {
      // Preserve the request key after a lost response and across page reloads.
      const id = sessionStorage.getItem(storageKey) ?? crypto.randomUUID()
      sessionStorage.setItem(storageKey, id)
      const result = await read(await fetch(`${base}/api/v1/driver/charging/sessions/${session.id}/${action}`, {
        method: 'POST', credentials: 'include', signal: abort.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: id }),
      }))
      if (!abort.signal.aborted) {
        if (!['Pending', 'Accepted'].includes(result.status)) sessionStorage.removeItem(storageKey)
        setCommand(result); setConfirming(false); setUncertainAction(null); refresh.current()
      }
    } catch (cause) {
      if (!abort.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'Không đọc được kết quả thao tác.')
        setUncertainAction(action)
      }
    } finally {
      if (!abort.signal.aborted) { setBusy(false); sending.current = false }
    }
  }

  const commandId = command?.id
  const commandStatus = command?.status
  useEffect(() => {
    if (commandStatus !== 'Pending') return
    const abort = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    async function poll() {
      try {
        const result = await read(await fetch(`${base}/api/v1/driver/charging/commands/${commandId}`, {
          credentials: 'include', signal: abort.signal,
        }))
        if (abort.signal.aborted) return
        if (!['Pending', 'Accepted'].includes(result.status) && submittedAction.current) {
          sessionStorage.removeItem(`csms:session-command:${session.id}:${submittedAction.current}`)
        }
        setCommand(result); refresh.current()
        if (result.status === 'Pending') timer = setTimeout(() => { void poll() }, 1000)
      } catch {
        if (!abort.signal.aborted) {
          setError('Không cập nhật được yêu cầu. Theo dõi trạng thái từ trụ hoặc tải lại trang.')
          timer = setTimeout(() => { void poll() }, 3000)
        }
      }
    }
    timer = setTimeout(() => { void poll() }, 1000)
    return () => { abort.abort(); clearTimeout(timer) }
  }, [commandId, commandStatus, session.id])

  const waiting = !!session.ended_at
  const stopPending = command?.status === 'Accepted' || command?.status === 'Pending'
  return <section className="driver-session-controls" aria-label="Kết thúc phiên sạc">
    {waiting ? <>
      <h3>Đã dừng sạc — vui lòng rút súng</h3>
      <p>Phí chiếm trụ vẫn áp dụng theo biểu giá và thời gian miễn phí. Hóa đơn được chốt khi trụ xác nhận đầu nối đã giải phóng.</p>
      <label className="driver-plug-confirm"><input type="checkbox" checked={unplugged} onChange={event => setUnplugged(event.target.checked)} /> Tôi đã rút súng khỏi xe</label>
      <p role="status">{unplugged ? 'Đã ghi nhận xác nhận của bạn. CSMS vẫn chờ tín hiệu rút súng từ trụ.' : 'Rút súng tại trụ để hoàn tất phiên.'}</p>
    </> : confirming ? <div className="driver-stop-confirm">
      <h3>Dừng sạc phiên #{session.id}?</h3>
      <p>Sau khi trụ dừng cấp điện, hãy rút súng. Chỉ xác nhận trên màn hình không kết thúc phí chiếm trụ.</p>
      <div className="driver-command-buttons"><button className="primary-button" disabled={busy} onClick={() => { void send('stop') }}>Xác nhận dừng sạc</button><button className="secondary-button" disabled={busy} onClick={() => setConfirming(false)}>Tiếp tục sạc</button></div>
    </div> : <button className="secondary-button" disabled={busy || stopPending || !!uncertainAction} onClick={() => setConfirming(true)}>Dừng sạc</button>}
    {session.demo_unplug_available && <button className="secondary-button driver-demo-unplug" disabled={busy || command?.status === 'Pending'} onClick={() => { void send('demo-unplug') }}>Mô phỏng rút súng · Demo</button>}
    {busy && <p role="status">Đang gửi yêu cầu đến trụ…</p>}
    {command && <p role="status">{labels[command.status] ?? 'Đang kiểm tra trạng thái yêu cầu.'}</p>}
    {error && <p role="alert">{error}</p>}
    {uncertainAction && <button className="secondary-button" disabled={busy} onClick={() => { void send(uncertainAction) }}>Kiểm tra lại yêu cầu</button>}
  </section>
}
