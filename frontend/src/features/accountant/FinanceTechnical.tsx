import { useEffect, useState } from 'react'
import { MeterChart, type MeterReading } from '../charging/MeterChart'
import { meterLocationLabel, meterUnitLabel } from '../charging/meterPresentation'
import { historyLabels, measurementLabels } from '../owner/ownerApi'
import { financeRequest, instant } from './financeApi'

export function FinanceTechnical({ id }: { id: number }) {
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [revision, setRevision] = useState(0)
  const [result, setResult] = useState<{ page: number; samples: {items: MeterReading[]; total_pages: number}; events: {id:string; action:string; occurred_at:string; details: {reason?:string}}[] }>()
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void Promise.all([
      financeRequest<{items: MeterReading[]; total_pages:number}>(`/charging/sessions/${id}/samples?page=${page}&page_size=100`, controller.signal),
      financeRequest<{id:string; action:string; occurred_at:string; details:{reason?:string}}[]>(`/charging/sessions/${id}/events`, controller.signal),
    ]).then(([samples, events]) => { if (!controller.signal.aborted) {setResult({page, samples, events});setError('')} })
      .catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Không tải được số đo.') })
    return () => controller.abort()
  }, [id, page, open, revision])
  return <details className="finance-panel finance-technical" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary>Số đo và lịch sử kỹ thuật</summary>
    {open && <div className="finance-technical-body">
      {error ? <div className="finance-error" role="alert">{error}<button onClick={() => setRevision(r=>r+1)}>Tải lại số đo</button></div> : !result || result.page !== page ? <p role="status">Đang tải số đo…</p> : <>
        <MeterChart readings={result.samples.items} sessionId={id}/>
        <details><summary>Bảng số đo gốc</summary><div className="finance-table-scroll"><table><caption>Số đo phiên #{id} — giữ đơn vị nguồn Wh/W để đối chiếu</caption><thead><tr><th>Thời điểm</th><th>Đại lượng / vị trí</th><th>Giá trị</th></tr></thead><tbody>{result.samples.items.map((s,i)=><tr key={i}><td>{instant(s.timestamp)}</td><td>{measurementLabels[s.measurand] ?? s.measurand} · {s.phase || 'Tổng'} / {meterLocationLabel(s.location)}</td><td>{Number(s.value).toLocaleString('vi-VN')} {meterUnitLabel(s.unit)}</td></tr>)}</tbody></table></div></details>
        {result.samples.total_pages > 1 && <nav className="finance-pagination" aria-label="Phân trang số đo"><button disabled={page===1} onClick={()=>setPage(p=>p-1)}>Số đo trước</button><span>Trang {page}/{result.samples.total_pages}</span><button disabled={page>=result.samples.total_pages} onClick={()=>setPage(p=>p+1)}>Số đo tiếp</button></nav>}
        <details><summary>Lịch sử phiên · {result.events.length} sự kiện</summary>{!result.events.length ? <p>Chưa có sự kiện.</p> : <ol className="finance-events">{result.events.map(event=><li key={event.id}><strong>{historyLabels[event.action] ?? event.action}</strong><span>{instant(event.occurred_at)}</span>{event.details.reason && <p>{event.details.reason}</p>}</li>)}</ol>}</details>
      </>}
    </div>}
  </details>
}
