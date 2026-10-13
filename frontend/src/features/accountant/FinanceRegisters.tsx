import { useState } from 'react'
import { reviewLabels } from '../owner/ownerApi'
import { financeHints, financeLink, financialLabels, instant, money, navigateFinance, type FinanceArea, type FinancialSession } from './financeApi'

function RecordLink({item,area,query,onOpen,label}: {item:FinancialSession;area:FinanceArea;query:string;onOpen:()=>void;label:string}){
  const params=new URLSearchParams(query);params.set('session',String(item.session_id))
  return <a className="finance-session-link" href={financeLink(area,params)} onClick={event=>{if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();onOpen();navigateFinance(area,params)}}>{label}</a>
}

export function InvoiceRegister({items,query,onOpen}: {items:FinancialSession[];query:string;onOpen:()=>void}){
  return <div className="finance-table-scroll"><table className="finance-invoice-register"><caption>Sổ chứng từ phí sạc nội bộ — tra cứu theo mã hóa đơn và thời điểm lập</caption><thead><tr><th>Chứng từ / tài xế</th><th>Lập hóa đơn / trạm</th><th>Thành tiền</th><th>Bằng chứng thanh toán</th></tr></thead><tbody>{items.map(item=><tr key={item.session_id}><td><strong className="finance-code">{item.invoice_id}</strong><span>{item.driver_email??'Chưa xác định tài xế'}</span><RecordLink item={item} area="invoices" query={query} onOpen={onOpen} label={`Phiên #${item.session_id}`}/></td><td><span>{instant(item.invoice_created_at)}</span><small>{item.station_name}</small></td><td className="finance-money">{money(item.invoice_total_vnd)}</td><td><span className={`finance-status is-${item.status}`}>{financialLabels[item.status]}</span><small>{item.ledger_id?`Sổ cái #${item.ledger_id} · ${money(item.debited_vnd)}`:item.status==='legacy_exempt'?'Miễn theo mốc chuyển đổi; không ghi nhận khoản thu':item.invoice_total_vnd==='0'?'Hóa đơn 0 đồng': 'Chưa có khoản trừ ví khớp hóa đơn'}</small></td></tr>)}</tbody></table></div>
}

function ReviewCase({item,query,onOpen}: {item:FinancialSession;query:string;onOpen:()=>void}){
  const [copied,setCopied]=useState(false)
  const [copyError,setCopyError]=useState(false)
  const reasons=item.review_reasons.map(reason=>reviewLabels[reason]??(reason==='settlement_ledger_mismatch'?'Hóa đơn và sổ cái chưa khớp':'Dữ liệu cần kiểm tra'))
  const report=`Phiên #${item.session_id}\nTrạm: ${item.station_name}\nTrụ: ${item.charge_point_code} · Đầu nối ${item.connector_number}\nTài xế: ${item.driver_email??'Chưa xác định'}\nKết thúc: ${instant(item.ended_at)}\nTrạng thái: ${financialLabels[item.status]}\nHóa đơn: ${item.invoice_id??'Chưa có'} · ${money(item.invoice_total_vnd)}\nTrừ ví khớp hóa đơn: ${money(item.debited_vnd)}\n${reasons.join('; ')}\n${financeHints[item.status]}`
  async function copy(){try{await navigator.clipboard.writeText(report);setCopied(true);setCopyError(false)}catch{setCopyError(true)}}
  return <article className="finance-review-case"><div className="finance-case-header"><RecordLink item={item} area="reconciliation" query={query} onOpen={onOpen} label={`Phiên #${item.session_id}`}/><span className={`finance-status is-${item.status}`}>{financialLabels[item.status]}</span></div><p><strong>{item.station_name}</strong> · {item.charge_point_code} · Đầu nối {item.connector_number}</p><p className="finance-muted">{item.ended_at?`Kết thúc: ${instant(item.ended_at)}`:`Bắt đầu: ${instant(item.started_at)}`} · {item.driver_email??'Chưa xác định tài xế'}</p>{reasons.length>0&&<ul>{reasons.map((reason,i)=><li key={i}>{reason}</li>)}</ul>}<p>{financeHints[item.status]}</p><dl className="finance-case-evidence"><div><dt>Hóa đơn</dt><dd>{money(item.invoice_total_vnd)}</dd></div><div><dt>Trừ ví khớp</dt><dd>{money(item.debited_vnd)}</dd></div></dl><div className="finance-case-actions"><RecordLink item={item} area="reconciliation" query={query} onOpen={onOpen} label="Kiểm tra hóa đơn & sổ cái"/><button onClick={()=>void copy()}>Sao chép hồ sơ</button><span role="status">{copied?'Đã sao chép để chuyển vận hành':''}</span></div>{copyError&&<details open><summary>Không sao chép được. Chọn nội dung để sao chép thủ công</summary><pre className="finance-case-report">{report}</pre></details>}</article>
}
export function ReconciliationQueue({items,query,onOpen}: {items:FinancialSession[];query:string;onOpen:()=>void}){
  return <div className="finance-review-queue">{items.map(item=><ReviewCase key={item.session_id} item={item} query={query} onOpen={onOpen}/>)}</div>
}
