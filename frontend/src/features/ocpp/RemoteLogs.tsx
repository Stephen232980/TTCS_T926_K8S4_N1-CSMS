import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

interface RemoteLogEntry {
  id: string; user_id: string; charge_point_id: string | null; session_id: number | null;
  command: string; result: string; created_at: string
}
interface Page { items: RemoteLogEntry[]; total: number; page: number; total_pages: number }

export function RemoteLogs() {
  const [filters, setFilters] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    async function fetchLogs() {
      const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
      try {
        const response = await fetch(`${base}/api/v1/remote-logs?page=${page}${filters}`, { credentials: 'include', signal: controller.signal })
        if (response.status === 401) notifySessionUnauthorized()
        if (!response.ok) {
          const body = await response.json().catch(() => ({})) as { detail?: unknown }
          throw new Error(typeof body.detail === 'string' ? body.detail : 'Không tải được nhật ký từ xa.')
        }
        const value = await response.json() as Page
        if (!controller.signal.aborted) { setData(value); setError('') }
      } catch (err: unknown) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Không tải được nhật ký từ xa.')
      }
    }
    void fetchLogs()
    return () => controller.abort()
  }, [page, filters, revision])

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const query = new URLSearchParams()
    for (const key of ['charge_point_id', 'user_id', 'from_at', 'to_at']) {
      const value = String(form.get(key) ?? '').trim()
      if (value) query.set(key, key.endsWith('_at') ? new Date(value).toISOString() : value)
    }
    setPage(1); setData(null); setFilters(`&${query}`); setRevision(r => r + 1)
  }

  return (
    <section className="control-audit" aria-label="Nhật ký lệnh từ xa">
      <h2>Nhật ký lệnh từ xa</h2><p>Mọi lệnh điều khiển từ xa được ghi nhật ký kèm người thực hiện.</p>
      <form className="control-audit__filters" onSubmit={apply}>
        <label>ID Trụ sạc<input name="charge_point_id" maxLength={36} placeholder="UUID" /></label>
        <label>ID Người dùng<input name="user_id" maxLength={36} placeholder="UUID" /></label>
        <label>Từ thời điểm<input name="from_at" type="datetime-local" /></label>
        <label>Đến thời điểm<input name="to_at" type="datetime-local" /></label>
        <button className="secondary-button">Lọc nhật ký</button>
      </form>
      {error && <p role="alert">{error}<button className="secondary-button" onClick={() => setRevision(r => r + 1)}>Tải lại nhật ký</button></p>}
      {!data && !error && <p role="status">Đang tải nhật ký…</p>}
      {data?.total === 0 && <p>Chưa có lệnh phù hợp với bộ lọc.</p>}
      <ol className="control-audit__entries">
        {data?.items.map(entry => (
          <li key={entry.id}>
            <strong>{entry.command}</strong>
            <p>Người thực hiện (ID): {entry.user_id}</p>
            {entry.charge_point_id && <p>Trụ (ID): {entry.charge_point_id}</p>}
            {entry.session_id !== null && <p>Phiên sạc (ID): {entry.session_id}</p>}
            <p>Kết quả: {entry.result}</p>
            <p>Thời gian: {new Date(entry.created_at).toLocaleString('vi-VN')}</p>
          </li>
        ))}
      </ol>
      {data && data.total_pages > 0 && (
        <div className="pagination">
          <button className="secondary-button" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Trang trước</button>
          <span>Trang {page}/{data.total_pages} · {data.total} lệnh</span>
          <button className="secondary-button" disabled={page >= data.total_pages} onClick={() => setPage(p => p + 1)}>Trang sau</button>
        </div>
      )}
    </section>
  )
}
