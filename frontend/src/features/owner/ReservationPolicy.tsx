import { useEffect, useRef, useState } from 'react'
import { ownerRequest } from './ownerApi'
import './stationOperation.css'

interface Policy { fee_vnd: number; version: number }
export function ReservationPolicy({ stationId }: { stationId: string }) {
  const [policy, setPolicy] = useState<Policy | null>(null)
  const [fee, setFee] = useState('0')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const mounted = useRef(true), sending = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    const controller = new AbortController()
    ownerRequest<Policy>(`/owner/stations/${encodeURIComponent(stationId)}/reservation-policy`, { signal: controller.signal }).then(next => {
      if (!Number.isInteger(next.fee_vnd) || !Number.isInteger(next.version)) throw new Error('Không đọc được chính sách phí.')
      if (!controller.signal.aborted) { setPolicy(next); setFee(String(next.fee_vnd)); setError('') }
    }).catch(() => { if (!controller.signal.aborted) setError('Không tải được chính sách phí. Tải lại trước khi lưu.') })
    return () => controller.abort()
  }, [stationId, revision])
  async function save() {
    const amount = Number(fee)
    if (sending.current || !policy || error || !Number.isInteger(amount) || amount < 0 || amount > 1000000) return
    sending.current = true; setBusy(true); setNotice('')
    try {
      const next = await ownerRequest<Policy>(`/owner/stations/${encodeURIComponent(stationId)}/reservation-policy`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({fee_vnd:amount,expected_version:policy.version})})
      if (mounted.current) { setPolicy(next); setNotice('Đã lưu. Mức phí mới chỉ áp dụng cho đặt chỗ được tạo sau khi khách xác nhận.') }
    } catch { if (mounted.current) setError('Chưa xác nhận được chính sách đã lưu. Tải lại để kiểm tra trước khi thử tiếp.') }
    finally { sending.current = false; if (mounted.current) setBusy(false) }
  }
  return <section className="owner-operation" aria-label="Phí không đến">
    <p>Áp dụng cho đặt chỗ mới. Tối đa 1.000.000đ.</p>
    <form onSubmit={event => {event.preventDefault(); void save()}}>
      <label>Phí không đến (đ)<input type="number" min={0} max={1000000} step={1} required value={fee} disabled={busy || !policy || !!error} onChange={event => setFee(event.target.value)} /></label>
      <button className="primary-button" disabled={busy || !policy || !!error}>{busy ? 'Đang lưu…' : 'Lưu phí không đến'}</button>
      <button type="button" className="secondary-button" disabled={busy} onClick={() => {setPolicy(null); setNotice(''); setRevision(value => value + 1)}}>Tải lại chính sách</button>
    </form>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </section>
}
