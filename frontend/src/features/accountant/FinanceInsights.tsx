import { useEffect, useState } from 'react'
import { ageLabels, financialLabels, financeRequest, money, navigateFinance, type FinanceArea, type FinanceInsightsData } from './financeApi'

const percentage = (value:string, maximum:bigint) => maximum > 0n ? Number(BigInt(value)*10000n/maximum)/100 : 0

function Timeline({data}: {data:FinanceInsightsData}) {
  const maximum=data.timeline.reduce((max,row)=>[BigInt(row.invoice_vnd),BigInt(row.debited_vnd),max].reduce((a,b)=>a>b?a:b),0n)
  return <figure className="finance-chart">
    <figcaption><h2>Hóa đơn và khoản trừ ví theo {data.grain==='month'?'tháng':'ngày'}</h2><p>Nhóm theo ngày bắt đầu phiên. Không phải dòng tiền phát sinh trong ngày.</p></figcaption>
    <div className="finance-chart-legend"><span><i className="is-invoice"/>Hóa đơn đã lưu</span><span><i className="is-debit"/>Trừ ví khớp hóa đơn</span></div>
    <div className="finance-column-scroll"><div className="finance-columns" role="img" aria-label="So sánh hóa đơn và khoản trừ ví; số liệu chi tiết ở bảng bên dưới">
      {data.timeline.map(row=><div className="finance-column-group" key={row.period}><div className="finance-column-pair"><span className="is-invoice" style={{height:`${percentage(row.invoice_vnd,maximum)}%`}}/><span className="is-debit" style={{height:`${percentage(row.debited_vnd,maximum)}%`}}/></div><span>{data.grain==='month'?row.period.slice(0,7):row.period.slice(5).split('-').reverse().join('/')}</span></div>)}
    </div></div>
    <p className="finance-muted">Mốc cao nhất: {money(maximum.toString())}. Cột trống tương ứng 0 đồng; chỉ liệt kê ngày/tháng có phiên.</p>
    <details className="finance-chart-data"><summary>Xem số liệu biểu đồ</summary><div className="finance-table-scroll"><table><caption>Toàn bộ kết quả lọc, không phụ thuộc phân trang</caption><thead><tr><th>Ngày / tháng bắt đầu</th><th>Số phiên</th><th>Hóa đơn</th><th>Trừ ví</th></tr></thead><tbody>{data.timeline.map(row=><tr key={row.period}><td>{row.period}</td><td>{row.sessions}</td><td>{money(row.invoice_vnd)}</td><td>{money(row.debited_vnd)}</td></tr>)}</tbody></table></div></details>
  </figure>
}

export function FinanceInsights({area,query,revision,onReady}: {area:FinanceArea;query:string;revision:number;onReady:()=>void}) {
  const [record,setRecord]=useState<{key:string;data?:FinanceInsightsData;error?:string}>()
  const [retry,setRetry]=useState(0)
  const params=new URLSearchParams(query);params.delete('page');params.delete('session')
  const path=`/finance/insights/${area}?${params}`
  const key=`${path}:${revision}:${retry}`
  useEffect(()=>{
    const controller=new AbortController()
    void financeRequest<FinanceInsightsData>(path,controller.signal).then(data=>{if(!controller.signal.aborted)setRecord({key,data})}).catch(error=>{if(!controller.signal.aborted)setRecord({key,error:error instanceof Error?error.message:'Không tải được biểu đồ.'})})
    return()=>controller.abort()
  },[key,path])
  const current=record?.key===key?record:undefined
  useEffect(()=>{if(current)onReady()},[current,onReady])
  if(!current)return <p role="status" className="finance-muted">Đang tổng hợp biểu đồ…</p>
  if(current.error)return <div className="finance-error"><p>Chưa tải được biểu đồ. {current.error} Danh sách bên dưới vẫn có thể tra cứu.</p><button onClick={()=>setRetry(n=>n+1)}>Tải lại biểu đồ</button></div>
  const data=current.data!
  if(!data.timeline.length)return <p className="finance-muted">Chưa có dữ liệu để vẽ biểu đồ cho bộ lọc này.</p>
  function filter(name:string,value:string){const next=new URLSearchParams(query);next.set(name,value);next.set('page','1');navigateFinance(area,next)}
  if(area==='sessions')return <div className="finance-analysis-grid"><Timeline data={data}/><section className="finance-chart"><h2>Phân bổ theo trạm</h2><p>Tổng hóa đơn của các phiên trong bộ lọc. Chọn trạm để tra cứu.</p><div className="finance-rank-list">{data.stations.map(row=>{
    const max=data.stations.reduce((a,b)=>BigInt(b.invoice_vnd)>a?BigInt(b.invoice_vnd):a,0n)
    return <button key={row.id} className="finance-rank" onClick={()=>filter('station_id',row.id)}><span>{row.name}<small>{row.sessions} phiên · Trừ ví {money(row.debited_vnd)}</small></span><strong>{money(row.invoice_vnd)}</strong><span className="finance-track"><i style={{width:`${percentage(row.invoice_vnd,max)}%`}}/></span></button>
  })}</div></section></div>
  if(area==='invoices'){
    const total=data.fees.reduce((sum,row)=>sum+BigInt(row.amount_vnd),0n)
    return <div className="finance-analysis-grid"><section className="finance-chart"><h2>Cơ cấu khoản phí đã lập</h2><p>Cộng các dòng chi tiết của hóa đơn trong bộ lọc.</p><div className="finance-fee-stack" role="img" aria-label={data.fees.map(row=>`${row.type==='energy'?'Tiền điện':'Phí chiếm trụ'}: ${money(row.amount_vnd)}`).join('; ')}>{data.fees.map(row=><span key={row.type} className={row.type==='energy'?'is-debit':'is-invoice'} style={{width:`${percentage(row.amount_vnd,total)}%`}}/>)}</div><dl className="finance-fee-breakdown">{data.fees.map(row=><div key={row.type}><dt>{row.type==='energy'?'Tiền điện':row.type==='idle'?'Phí chiếm trụ':row.type}</dt><dd>{money(row.amount_vnd)} <small>{percentage(row.amount_vnd,total).toLocaleString('vi-VN',{maximumFractionDigits:1})}%</small></dd></div>)}</dl>{!data.fees.length&&<p>Chưa có dòng chi tiết khoản phí.</p>}<p className="finance-muted">Tổng dòng chi tiết: {money(total.toString())}. Hóa đơn thiếu dòng chi tiết cần được kiểm tra riêng.</p></section><section className="finance-chart"><h2>Tình trạng chứng từ</h2><p>Chọn trạng thái để mở sổ hóa đơn tương ứng.</p><div className="finance-rank-list">{data.statuses.map(row=><button className="finance-rank" key={row.status} onClick={()=>filter('status',row.status)}><span>{financialLabels[row.status]}</span><strong>{row.count} hóa đơn</strong><small>{money(row.invoice_vnd)}</small></button>)}</div></section></div>
  }
  const max=Math.max(...data.aging.map(row=>row.count),1)
  return <div className="finance-analysis-grid"><section className="finance-chart"><h2>Thời gian chờ đối chiếu</h2><p>Tính từ khi kết thúc phiên; phiên đang mở tính từ lúc bắt đầu. Chọn nhóm để lọc hồ sơ.</p><div className="finance-rank-list">{Object.entries(ageLabels).map(([bucket,label])=>{const row=data.aging.find(r=>r.bucket===bucket);return <button key={bucket} className="finance-rank" onClick={()=>filter('age',bucket)} aria-pressed={params.get('age')===bucket}><span>{label}</span><strong>{row?.count??0} phiên</strong><span className="finance-track"><i style={{width:`${(row?.count??0)/max*100}%`}}/></span><small>Hóa đơn liên quan: {money(row?.invoice_vnd??'0')}</small></button>})}</div></section><section className="finance-chart"><h2>Phân loại việc cần kiểm tra</h2><p>Ưu tiên dữ liệu bất thường; trạng thái chờ chưa đồng nghĩa có lỗi.</p><div className="finance-rank-list">{data.statuses.map(row=><button key={row.status} className="finance-rank" onClick={()=>filter('status',row.status)}><span>{financialLabels[row.status]}</span><strong>{row.count} phiên</strong></button>)}</div><p className="finance-muted">Danh sách bên dưới ưu tiên phiên cần kiểm tra, sau đó phiên chờ lâu nhất. Không đánh dấu hoàn tất khi chưa có bằng chứng quyết toán.</p></section></div>
}
