import { useCallback, useState } from 'react'
import { adminRequest, dateTime, numberText, queryString, vietnamInstant } from './adminApi'
import { ErrorNotice, Pagination } from './AdminShared'
import { useResource } from './useResource'
import type { AuthenticatedUser } from '../auth/model/auth'

interface Entry {
  id: string; actor_id: string | null; driver_id: string | null; wallet_id: string | null
  action: string; occurred_at: string; amount_vnd: number | null
  before_balance_vnd: number | null; after_balance_vnd: number | null
  reason: string | null; legacy: boolean; ledger_id: number | null
  reference_type: string | null; reference_id: string | null; reservation_id: string | null
  before_decision: string | null; decision: string | null
}
const actions: Record<string, string> = { 'wallet.manual_topup': 'Nạp tay', 'wallet.adjusted': 'Điều chỉnh', 'wallet.cache_repaired': 'Sửa số dư lưu tạm', 'wallet.unlocked': 'Mở khóa ví', 'reservation.fee_decided': 'Quyết định phí đặt chỗ' }
const missing = 'Chưa ghi nhận'
const initial = { driver_id: '', wallet_id: '', action: '', from: '', to: '' }
export function AdminWalletAudit({ currentUser }: { currentUser: AuthenticatedUser }) {
  return currentUser.roles.includes('admin') ? <WalletAudit key={currentUser.id} /> : <p role="alert">Bạn không có quyền xem nhật ký ví.</p>
}
function WalletAudit() {
  const [draft, setDraft] = useState(initial)
  const [filters, setFilters] = useState(initial)
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')
  const resource = useResource(useCallback(signal => adminRequest<{ items: Entry[]; total: number; total_pages: number }>(`/admin/wallet-audit?${queryString({ driver_id: filters.driver_id.trim(), wallet_id: filters.wallet_id.trim(), action: filters.action, from_at: vietnamInstant(filters.from), to_at: vietnamInstant(filters.to), page, page_size: 50 })}`, { signal }), [filters, page]))
  const money = (value: number | null) => value === null ? '—' : `${numberText(value)} VND`
  return <>
    <header className="admin-heading"><h1>Nhật ký ví</h1></header>
    <form className="admin-filters admin-audit-filters" onSubmit={event => {
      event.preventDefault()
      if (draft.from && draft.to && draft.from > draft.to) { setError('Thời gian bắt đầu phải trước thời gian kết thúc.'); return }
      setError(''); setFilters({ ...draft }); setPage(1)
    }}>
      <label>Mã tài xế<input value={draft.driver_id} onChange={e => setDraft({ ...draft, driver_id: e.target.value })} /></label>
      <label>Mã ví<input value={draft.wallet_id} onChange={e => setDraft({ ...draft, wallet_id: e.target.value })} /></label>
      <label>Thao tác<select value={draft.action} onChange={e => setDraft({ ...draft, action: e.target.value })}><option value="">Tất cả thao tác</option>{Object.entries(actions).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
      <label>Từ (giờ VN)<input type="datetime-local" value={draft.from} onChange={e => setDraft({ ...draft, from: e.target.value })} /></label>
      <label>Đến (giờ VN)<input type="datetime-local" value={draft.to} onChange={e => setDraft({ ...draft, to: e.target.value })} /></label>
      <button className="admin-primary" type="submit">Lọc</button>
      <button type="button" onClick={() => { setDraft(initial); setFilters(initial); setPage(1); setError(''); resource.reload() }}>Đặt lại</button>
    </form>
    <ErrorNotice error={error || resource.error} onRetry={resource.reload} />
    {resource.loading && <p role="status">Đang tải nhật ký ví…</p>}
    {resource.data && <section className="admin-panel admin-wallet-audit" aria-label="Nhật ký giao dịch ví">
      {!resource.data.items.length && <p>Không có nhật ký phù hợp.</p>}
      {resource.data.items.map(entry => <details key={entry.id} className="admin-wallet-audit-row">
        <summary>{dateTime(entry.occurred_at)} · {actions[entry.action]} · {money(entry.amount_vnd)}</summary>
        <dl className="admin-topup-summary" style={{ overflowWrap: 'anywhere' }}>
          <dt>Người thực hiện</dt><dd>{entry.actor_id ?? 'Hệ thống'}</dd>
          <dt>Tài xế</dt><dd>{entry.driver_id ?? missing}</dd><dt>Ví</dt><dd>{entry.wallet_id ?? missing}</dd>
          <dt>Số dư trước</dt><dd>{money(entry.before_balance_vnd)}</dd><dt>Số dư sau</dt><dd>{money(entry.after_balance_vnd)}</dd>
          <dt>Lý do</dt><dd>{entry.reason ?? missing}</dd>
          <dt>Dòng sổ cái</dt><dd>{entry.ledger_id === null ? 'Không có' : `#${entry.ledger_id}`}</dd>
          <dt>Chứng từ</dt><dd>{entry.reference_id ? `${entry.reference_type}: ${entry.reference_id}` : 'Không có'}</dd>
          <dt>Đặt chỗ</dt><dd>{entry.reservation_id ?? 'Không có'}</dd>
          {entry.decision && <><dt>Quyết định phí</dt><dd>{entry.before_decision ?? missing} → {entry.decision}</dd></>}
          <dt>Mã nhật ký</dt><dd>{entry.id}</dd>
        </dl>
        {entry.legacy && <p className="admin-muted">Bản ghi cũ · Trường thiếu chưa được ghi nhận.</p>}
      </details>)}
      <Pagination page={page} totalPages={resource.data.total_pages} total={resource.data.total} busy={resource.loading} onPage={setPage} />
    </section>}
  </>
}
