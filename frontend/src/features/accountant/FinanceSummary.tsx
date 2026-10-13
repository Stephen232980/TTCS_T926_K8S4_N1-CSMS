import { money, type FinanceArea, type FinancialPage } from './financeApi'

export function FinanceSummary({area,list}: {area:FinanceArea;list:FinancialPage}) {
  const summary=list.summary
  const metrics=area==='sessions' ? [
    ['Tổng hóa đơn đã lưu',money(summary.invoice_total_vnd),`${summary.invoices} hóa đơn · chưa đồng nghĩa đã thu`],
    ['Đã trừ ví khớp hóa đơn',money(summary.debited_total_vnd),'Không gồm miễn quyết toán dữ liệu cũ'],
    ['Phiên chờ / cần kiểm tra',summary.awaiting_settlement.toLocaleString('vi-VN'),'Trong toàn bộ kết quả lọc'],
  ] : area==='invoices' ? [
    ['Chứng từ đã lập',summary.invoices.toLocaleString('vi-VN'),'Hóa đơn nội bộ khớp bộ lọc'],
    ['Tổng giá trị chứng từ',money(summary.invoice_total_vnd),'Bao gồm chứng từ miễn quyết toán'],
    ['Đã thu qua ví',money(summary.debited_total_vnd),'Đối chiếu bằng sổ cái, không suy ra từ hóa đơn'],
  ] : [
    ['Hồ sơ cần đối chiếu',list.total.toLocaleString('vi-VN'),'Dữ liệu bất thường hoặc phiên kết thúc chưa quyết toán'],
    ['Giá trị hóa đơn liên quan',money(summary.invoice_total_vnd),'Không phải số tiền còn phải thu'],
    ['Khoản trừ ví đã khớp',money(summary.debited_total_vnd),'Kiểm tra bằng chứng trước khi chuyển xử lý'],
  ]
  return <dl className="finance-summary" aria-label="Tổng hợp toàn bộ kết quả lọc">{metrics.map(([label,value,note])=><div key={label}><dt>{label}</dt><dd>{value}</dd><small>{note}</small></div>)}</dl>
}
