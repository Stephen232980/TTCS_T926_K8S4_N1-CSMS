import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { controlRequest, controlStatuses } from './controlApi'

interface Entry { id: string; actor: string; charge_point_code: string; transaction_id: number | null; action: string; payload: { type?: string }; created_at: string; status: string; received_at: string | null }
interface Page { items: Entry[]; total: number; page: number; total_pages: number }
export function ControlAudit() {
  const [filters, setFilters] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    void controlRequest<Page>(`/control-audit?page=${page}${filters}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) { setData(value); setError('') } }).catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Không tải được nhật ký.') })
    return () => controller.abort()
  }, [page, filters, revision])
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const query = new URLSearchParams()
    for (const key of ['charge_point_code', 'actor_email', 'from_at', 'to_at']) {
      const value = String(form.get(key) ?? '').trim()
      if (value) query.set(key, key.endsWith('_at') ? new Date(value).toISOString() : value)
    }
    setPage(1); setData(null); setFilters(`&${query}`); setRevision(r => r + 1)
  }
  return <section className="control-audit" aria-label="Nhật ký điều khiển">
    <h2>Nhật ký điều khiển</h2><p>Ai gửi lệnh, tới trụ nào và trụ phản hồi ra sao. Nhật ký được giữ nguyên sau khi ghi.</p>
    <form className="control-audit__filters" onSubmit={apply}>
      <label>Mã trụ<input name="charge_point_code" maxLength={64} /></label><label>Email người thực hiện<input name="actor_email" type="email" /></label>
      <label>Từ thời điểm<input name="from_at" type="datetime-local" /></label><label>Đến thời điểm<input name="to_at" type="datetime-local" /></label><button className="secondary-button">Lọc nhật ký</button>
    </form>
    {error && <p role="alert">{error}<button className="secondary-button" onClick={() => setRevision(r => r + 1)}>Tải lại nhật ký</button></p>}
    {!data && !error && <p role="status">Đang tải nhật ký…</p>}
    {data?.total === 0 && <p>Chưa có lệnh phù hợp với bộ lọc.</p>}
    <ol className="control-audit__entries">{data?.items.map(entry => <li key={entry.id}>
      <strong>{entry.action === 'Reset' ? `Khởi động ${entry.payload.type === 'Hard' ? 'cứng' : 'mềm'}` : entry.action === 'RemoteStartTransaction' ? 'Bắt đầu từ ứng dụng' : 'Dừng từ xa'} · {entry.charge_point_code}{entry.transaction_id !== null && ` · Phiên #${entry.transaction_id}`}</strong>
      <p>{entry.actor} · {new Date(entry.created_at).toLocaleString('vi-VN')}</p><p>{controlStatuses[entry.status] ?? entry.status}</p>
      {entry.received_at && <p>Kết quả lúc {new Date(entry.received_at).toLocaleString('vi-VN')}</p>}
    </li>)}</ol>
    {data && <div className="pagination"><button className="secondary-button" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Trang trước</button><span>Trang {page}/{data.total_pages} · {data.total} lệnh</span><button className="secondary-button" disabled={page >= data.total_pages} onClick={() => setPage(p => p + 1)}>Trang sau</button></div>}
  </section>
}
