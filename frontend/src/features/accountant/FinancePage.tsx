import { useCallback, useEffect, useRef, useState, type FormEvent, type ChangeEvent } from 'react'
import { reviewLabels } from '../owner/ownerApi'
import { FinanceTechnical } from './FinanceTechnical'
import { FinanceInsights } from './FinanceInsights'
import { InvoiceRegister, ReconciliationQueue } from './FinanceRegisters'
import { ReconciliationRunsView } from './ReconciliationRunsView'
import { FinanceSummary } from './FinanceSummary'
import { ageLabels, energy, exportAccountantRevenueCsv, financeHints, financeLink, financeRequest, financeTitles, financialLabels, financialQuery, instant, money, navigateFinance, type FinanceArea, type FinancialDetail, type FinancialPage, type FinancialSession, type StationOption } from './financeApi'


function Status({ item }: {item:FinancialSession}) {
  return <span className={`finance-status is-${item.status}`}>{financialLabels[item.status]}</span>
}

function Filters({ area, params, stations }: {area:FinanceArea; params:URLSearchParams; stations:StationOption[]}) {
  const [draft, setDraft] = useState(() => Object.fromEntries(['q','station_id','date_from','date_to','status','age'].map(key=>[key,params.get(key) ?? ''])))
  const [error, setError] = useState('')
  const field = (key:string) => ({value:draft[key],onChange:(e:ChangeEvent<HTMLInputElement | HTMLSelectElement>)=>setDraft({...draft,[key]:e.target.value})})
  function apply(e:FormEvent) {
    e.preventDefault()
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {setError('Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.');return}
    const next = new URLSearchParams()
    for (const [key,value] of Object.entries(draft)) if (value.trim()) next.set(key,value.trim())
    next.set('page','1');setError('');navigateFinance(area,next)
  }
  return <form className="finance-filters finance-panel" onSubmit={apply} aria-label="Bộ lọc kế toán">
    <label className="finance-search">Tìm phiên hoặc hóa đơn<input type="search" maxLength={160} placeholder="Mã phiên, hóa đơn, trạm, trụ, email tài xế" {...field('q')}/></label>
    <label>Trạm<select {...field('station_id')}><option value="">Tất cả trạm</option>{stations.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
    <label>Từ ngày<input type="date" {...field('date_from')}/></label>
    <label>Đến ngày<input type="date" {...field('date_to')}/></label>
    <label>Thanh toán<select {...field('status')}><option value="">Tất cả trạng thái</option>{Object.entries(financialLabels).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
    {area==='reconciliation'&&<label>Thời gian chờ<select {...field('age')}><option value="">Tất cả thời gian</option>{Object.entries(ageLabels).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>}
    <div className="finance-filter-actions"><button className="accountant-primary" type="submit">Áp dụng</button><button type="button" onClick={()=>{setDraft({q:'',station_id:'',date_from:'',date_to:'',status:'',age:''});setError('');navigateFinance(area,new URLSearchParams())}}>Xóa lọc</button></div>
    <p className="finance-filter-note">Tìm trên toàn hệ thống. Khoảng ngày tính theo {area==='invoices'?'thời điểm lập hóa đơn':'thời điểm bắt đầu phiên'}, giờ Việt Nam.</p>
    {error && <p className="finance-error" role="alert">{error}</p>}
  </form>
}

function Detail({ item, back, onBack }: {item:FinancialDetail; back:string; onBack:()=>void}) {
  const reasons = item.review_reasons.map(reason=>reviewLabels[reason] ?? (reason==='settlement_ledger_mismatch' ? 'Hóa đơn và sổ cái chưa khớp' : 'Dữ liệu cần kiểm tra'))
  return <>
    <div className="finance-detail-heading"><a className="finance-button navigation-link" href={back} onClick={event=>{if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();onBack()}}>← Quay lại danh sách</a><Status item={item}/></div>
    <section className="finance-panel finance-session-detail">
      <div className="finance-section-heading"><div><h2>Phiên #{item.session_id}</h2><p>{item.station_name} · {item.charge_point_code} · Đầu nối {item.connector_number}</p></div><strong>{money(item.invoice_total_vnd)}</strong></div>
      <p className={`finance-explanation${item.status==='needs_review' ? ' is-warning' : ''}`}>{financeHints[item.status]}</p>
      {reasons.length>0 && <details className="finance-reasons"><summary>Lý do được ghi nhận · {reasons.length}</summary><ul>{reasons.map((reason,i)=><li key={i}>{reason}</li>)}</ul><p>Kế toán chỉ đối chiếu dữ liệu. Gửi mã phiên #{item.session_id} cho bộ phận vận hành nếu cần xử lý.</p></details>}
      <dl className="finance-facts"><div><dt>Tài xế</dt><dd>{item.driver_email ?? 'Chưa xác định'}</dd></div><div><dt>Điện năng phiên</dt><dd>{energy(item.energy_kwh)}</dd></div><div><dt>Bắt đầu</dt><dd>{instant(item.started_at)}</dd></div><div><dt>Kết thúc</dt><dd>{item.ended_at ? instant(item.ended_at) : 'Đang sạc'}</dd></div><div><dt>Xác nhận rút súng</dt><dd>{instant(item.connector_released_at)}</dd></div><div><dt>Hoàn tất quyết toán</dt><dd>{instant(item.settlement_completed_at)}</dd></div></dl>
    </section>
    <section className="finance-panel finance-invoice-detail">
      <div className="finance-section-heading"><h2>Hóa đơn phí sạc</h2><span>Chứng từ nội bộ CSMS</span></div>
      {item.invoice_id ? <>
        <dl className="finance-facts"><div><dt>Mã hóa đơn</dt><dd className="finance-code">{item.invoice_id}</dd></div><div><dt>Lập lúc</dt><dd>{instant(item.invoice_created_at)}</dd></div></dl>
        <div className="finance-table-scroll"><table><caption>Chi tiết tiền điện và phí chiếm trụ — số tiền đã lưu</caption><thead><tr><th>Khoản phí / khoảng áp dụng</th><th>Điện năng</th><th>Đơn giá</th><th>Thành tiền</th></tr></thead><tbody>{item.lines.map(line=><tr key={line.id}><td><strong>{line.line_type==='energy'?'Tiền điện':'Phí chiếm trụ'}</strong><small>{instant(line.started_at)} → {instant(line.ended_at)}</small><small>{line.band_label}{line.interpolated ? ' · Điện năng nội suy' : ''}</small></td><td>{line.line_type==='energy' ? energy(line.energy_kwh) : '—'}</td><td>{money(line.rate_vnd)}/{line.line_type==='energy'?'kWh':'phút'}</td><td>{money(line.amount_vnd)}</td></tr>)}</tbody></table></div>
        {!item.lines.length && <p>Không có dòng chi tiết trong hóa đơn đã lưu.</p>}
        <div className="finance-total"><span>Tổng hóa đơn</span><strong>{money(item.invoice_total_vnd)}</strong></div>
        <p className="finance-muted">{item.rounding_rule ?? 'Không có mô tả quy tắc làm tròn.'} Đây không phải hóa đơn điện tử được phát hành qua cơ quan thuế.</p>
      </> : <p>Chưa có hóa đơn được lưu cho phiên này. {financeHints[item.status]}</p>}
    </section>
    <section className="finance-panel finance-ledger-detail"><h2>Đối chiếu khoản trừ ví</h2><dl className="finance-facts"><div><dt>Đã trừ ví khớp hóa đơn</dt><dd>{money(item.debited_vnd)}</dd></div><div><dt>Giao dịch sổ cái</dt><dd>{item.ledger_id ? `#${item.ledger_id}` : 'Không có khoản trừ ví'}</dd></div>{item.ledger_id && <><div><dt>Biến động ghi trong sổ cái</dt><dd>{money(item.ledger_amount_vnd)}</dd></div><div><dt>Ghi nhận lúc</dt><dd>{instant(item.debited_at)}</dd></div><div><dt>Tham chiếu</dt><dd>{item.ledger_reference_type} · Phiên #{item.session_id}</dd></div></>}</dl><p className="finance-muted">Hóa đơn và sổ cái là dữ liệu đã lưu. Màn hình này không tạo hóa đơn, trừ tiền hoặc sửa giao dịch.</p></section>
    <FinanceTechnical id={item.session_id}/>
  </>
}

export function FinancePage({ area }: {area:FinanceArea}) {
  const [hash, setHash] = useState(()=>window.location.hash)
  const [revision,setRevision] = useState(0)
  const [chartsKey,setChartsKey] = useState('')
  const [filtersOpen,setFiltersOpen] = useState(()=>window.innerWidth>800)
  const [stations,setStations] = useState<StationOption[]>([])
  const [stationsError,setStationsError] = useState('')
  const [record,setRecord] = useState<{key:string; list?:FinancialPage; detail?:FinancialDetail; error?:string; at?:string}>()
  const restored = useRef(false)
  useEffect(()=>{const change=()=>{restored.current=false;setHash(window.location.hash)};window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change)},[])
  useEffect(()=>{
    const previous=window.history.scrollRestoration
    window.history.scrollRestoration='manual'
    return()=>{window.history.scrollRestoration=previous}
  },[])
  const params = financialQuery(hash)
  const selected = params.get('session')
  const listParams = new URLSearchParams(params);listParams.delete('session')
  const query = new URLSearchParams(listParams)
  if(area==='reconciliation')query.set('attention','true')
  const path = selected ? `/finance/sessions/${encodeURIComponent(selected)}` : `/finance/${area==='invoices'?'invoices':'sessions'}?${query}`
  const key = `${path}:${revision}`
  const chartsReady=useCallback(()=>setChartsKey(key),[key])
  useEffect(()=>{
    if (area === 'runs') return
    const controller=new AbortController()
    void financeRequest<FinancialPage|FinancialDetail>(path,controller.signal).then(data=>{
      if(!controller.signal.aborted)setRecord('items' in data ? {key,list:data,at:new Date().toISOString()} : {key,detail:data,at:new Date().toISOString()})
    }).catch(error=>{if(!controller.signal.aborted)setRecord({key,error:error instanceof Error ? error.message : 'Không tải được dữ liệu.'})})
    return()=>controller.abort()
  },[path,key,area])
  useEffect(()=>{
    const controller=new AbortController()
    void financeRequest<{items:StationOption[]}>('/finance/stations',controller.signal).then(data=>{if(!controller.signal.aborted){setStations(data.items);setStationsError('')}}).catch(()=>{if(!controller.signal.aborted)setStationsError('Chưa tải được danh sách trạm. Bạn vẫn có thể tìm theo mã phiên hoặc email, hoặc bấm Làm mới.')})
    return()=>controller.abort()
  },[revision])
  const current=record?.key===key ? record : undefined
  useEffect(()=>{
    if(selected || !current?.list || chartsKey!==key || restored.current)return
    let layoutFrame=0
    const frame=requestAnimationFrame(()=>{layoutFrame=requestAnimationFrame(()=>{const saved=window.history.state?.accountingScroll;const main=document.querySelector('.accountant-page');if(saved&&main){main.scrollTop=saved.main;window.scrollTo({top:saved.window,behavior:'instant'})}restored.current=true})})
    return()=>{cancelAnimationFrame(frame);cancelAnimationFrame(layoutFrame)}
  },[selected,current,chartsKey,key])
  function rememberScroll(){window.history.replaceState({...window.history.state,accountingScroll:{main:document.querySelector('.accountant-page')?.scrollTop??0,window:window.scrollY}},'')}
  function goPage(page:number){const next=new URLSearchParams(listParams);next.set('page',String(page));window.history.replaceState({...window.history.state,accountingScroll:{main:0,window:0}},'');navigateFinance(area,next)}
  const [exportingRevenue, setExportingRevenue] = useState(false)
  const list=current?.list

  const handleExportRevenue = async () => {
    setExportingRevenue(true)
    try {
      const dateFrom = params.get('date_from') || undefined
      const dateTo = params.get('date_to') || undefined
      const periodParam = params.get('period')
      const period = periodParam || (dateFrom || dateTo ? 'custom' : 'month')
      await exportAccountantRevenueCsv({
        period,
        date_from: dateFrom,
        date_to: dateTo,
        station_id: params.get('station_id') || undefined,
      })
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Xuất CSV thất bại.')
    } finally {
      setExportingRevenue(false)
    }
  }

  if (area === 'runs') {
    return <ReconciliationRunsView stations={stations} />
  }

  return <section className="finance-workspace" aria-labelledby="finance-title">
    <div className="finance-sticky-header">
    <header className="finance-heading">
      <div>
        <h1 id="finance-title">{financeTitles[area]}</h1>
        <p>{area==='sessions'?'Theo dõi phiên, hóa đơn và khoản trừ ví trên toàn hệ thống.':area==='invoices'?'Tra cứu hóa đơn phí sạc đã lưu và chi tiết từng khoản phí.':'Theo dõi phiên có dữ liệu cần kiểm tra hoặc đã kết thúc nhưng chưa quyết toán.'}</p>
      </div>
      <div className="finance-heading-actions">
        <button type="button" className="finance-button" onClick={handleExportRevenue} disabled={exportingRevenue} aria-label="Xuất CSV báo cáo doanh thu">
          {exportingRevenue ? 'Đang xuất…' : 'Xuất CSV doanh thu'}
        </button>
        <button type="button" onClick={()=>setRevision(r=>r+1)}>Làm mới</button>
      </div>
    </header>

    <p className="finance-readonly">Chỉ đọc · Không phát hành hóa đơn điện tử hoặc đối soát đối tác.{current?.at && <span> Tải lúc {instant(current.at)}</span>}</p>
    {!selected && <>
      <details className="finance-filter-disclosure" open={filtersOpen} onToggle={event=>setFiltersOpen(event.currentTarget.open)}><summary>Tra cứu & bộ lọc{['q','station_id','date_from','date_to','status','age'].some(k=>params.get(k)) && <span>Đang áp dụng bộ lọc</span>}</summary><Filters key={listParams.toString()} area={area} params={listParams} stations={stations}/></details>
      {stationsError && <p className="finance-muted" role="status">{stationsError}</p>}
    </>}
    {!selected && list && <FinanceSummary area={area} list={list}/>}
    </div>
    {!current ? <div className="finance-panel finance-empty" role="status">Đang tải dữ liệu kế toán…</div> : current.error ? <div className="finance-error" role="alert"><p>{current.error}</p><button onClick={()=>setRevision(r=>r+1)}>Thử lại</button>{selected&&<a href={financeLink(area,listParams)}>Quay lại danh sách</a>}</div> : current.detail ? <Detail item={current.detail} back={financeLink(area,listParams)} onBack={()=>navigateFinance(area,listParams)}/> : list && <>
      <FinanceInsights area={area} query={listParams.toString()} revision={revision} onReady={chartsReady}/>

      {area==='reconciliation'&&<p className="finance-explanation">Trạng thái chờ có thể đang được hệ thống xử lý tự động. Đây không phải thao tác đánh dấu đã xử lý hoặc đối soát với đối tác.</p>}
      <section className="finance-panel finance-list-panel" aria-label="Kết quả tra cứu">
        <div className="finance-section-heading"><h2>{list.total.toLocaleString('vi-VN')} {area==='invoices'?'hóa đơn':'phiên'}</h2><span>{area==='invoices'?'Chứng từ mới lập trước':area==='reconciliation'?'Cần kiểm tra trước · chờ lâu trước':'Phiên mới nhất trước'} · Toàn bộ kết quả lọc</span></div>
        {list.items.length ? area==='invoices' ? <InvoiceRegister items={list.items} query={listParams.toString()} onOpen={rememberScroll}/> : area==='reconciliation' ? <ReconciliationQueue items={list.items} query={listParams.toString()} onOpen={rememberScroll}/> : <div className="finance-table-scroll"><table className="finance-session-table"><caption>{financeTitles[area]} — trang {list.page}/{list.total_pages}</caption><thead><tr><th>Phiên / trạm</th><th>Thời gian / điện năng</th><th>Tổng hóa đơn</th><th>Đã trừ ví</th><th>Thanh toán</th></tr></thead><tbody>{list.items.map(item=>{const next=new URLSearchParams(listParams);next.set('session',String(item.session_id));return <tr key={item.session_id}><td data-label="Phiên / trạm"><a className="finance-session-link" href={financeLink(area,next)} onClick={event=>{if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();rememberScroll();navigateFinance(area,next)}}>Phiên #{item.session_id}</a><span>{item.station_name}</span><small>{item.charge_point_code} · Đầu nối {item.connector_number}</small><small>{item.driver_email ?? 'Chưa xác định tài xế'}</small></td><td data-label="Thời gian / điện năng"><span>{instant(item.started_at)}</span><small>{item.ended_at ? `Kết thúc: ${instant(item.ended_at)}` : 'Phiên đang mở'}</small><strong>{energy(item.energy_kwh)}</strong></td><td data-label="Tổng hóa đơn" className="finance-money">{money(item.invoice_total_vnd)}</td><td data-label="Đã trừ ví" className="finance-money">{money(item.debited_vnd)}</td><td data-label="Thanh toán"><Status item={item}/></td></tr>})}</tbody></table></div> : <div className="finance-empty"><h3>{Number(params.get('page'))>list.total_pages?'Trang này không còn kết quả':area==='reconciliation'?'Không có phiên cần đối chiếu khớp bộ lọc':area==='invoices'?'Không có hóa đơn khớp bộ lọc':'Không có phiên khớp bộ lọc'}</h3><p>Thử đổi khoảng ngày, trạng thái hoặc xóa bộ lọc.</p><button onClick={()=>navigateFinance(area,new URLSearchParams())}>Xóa bộ lọc</button></div>}
        <nav className="finance-pagination" aria-label="Phân trang kế toán"><span>Trang {list.page} / {list.total_pages} · {list.items.length} kết quả hiển thị</span><div><button disabled={list.page===1} onClick={()=>goPage(list.page-1)}>Trang trước</button><button disabled={list.page>=list.total_pages} onClick={()=>goPage(list.page+1)}>Trang sau</button></div></nav>
      </section>
    </>}
  </section>
}
