import { useCallback, useState } from 'react'
import {
  adminRequest,
  dateTime,
  queryString,
  roleNames,
  statusNames,
  vietnamInstant,
  type AccountAudit,
  type AccountState,
  type ControlAudit,
  type Page,
} from './adminApi'
import { ErrorNotice, Pagination } from './AdminShared'
import { useResource } from './useResource'

type Entry = {
  id: string
  actor: string
  target: string
  action: string
  time: string
  control?: ControlAudit
  account?: AccountAudit
}
const actionNames: Record<string, string> = {
  Reset: 'Khởi động lại trụ',
  RemoteStartTransaction: 'Bắt đầu sạc từ xa',
  RemoteStopTransaction: 'Dừng sạc từ xa',
  account_created: 'Cấp tài khoản',
  account_updated: 'Cập nhật tài khoản',
}
const resultNames: Record<string, string> = {
  Accepted: 'Đã chấp nhận',
  Rejected: 'Từ chối',
  Pending: 'Đang chờ',
  Offline: 'Ngoại tuyến',
  Timeout: 'Hết thời gian chờ',
  Disconnected: 'Mất kết nối',
  ProtocolError: 'Lỗi giao thức',
}
// datetime-local values are explicitly interpreted in Vietnam time, independently of browser timezone.
const initial = { actor: '', chargePoint: '', action: '', from: '', to: '' }
export function AdminAudit() {
  const [source, setSource] = useState<'control' | 'account'>('control')
  const [draft, setDraft] = useState(initial)
  const [filters, setFilters] = useState(initial)
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [validation, setValidation] = useState('')
  const resource = useResource(
    useCallback(
      async (signal) => {
        const params = {
          page,
          page_size: 20,
          actor_email: filters.actor.trim(),
          from_at: vietnamInstant(filters.from),
          to_at: vietnamInstant(filters.to),
        }
        if (source === 'account') {
          const data = await adminRequest<Page<AccountAudit>>(
            `/admin/account-audit?${queryString({ ...params, action: filters.action })}`,
            { signal },
          )
          return {
            ...data,
            items: data.items.map(
              (a) =>
                ({
                  id: a.id,
                  actor: a.actor_email,
                  target: a.after.email,
                  action: a.action,
                  time: a.created_at,
                  account: a,
                }) as Entry,
            ),
          }
        }
        const data = await adminRequest<Page<ControlAudit>>(
          `/ocpp/control-audit?${queryString({ ...params, charge_point_code: filters.chargePoint.trim() })}`,
          { signal },
        )
        return {
          ...data,
          items: data.items.map(
            (c) =>
              ({
                id: c.id,
                actor: c.actor,
                target: c.charge_point_code,
                action: c.action,
                time: c.created_at,
                control: c,
              }) as Entry,
          ),
        }
      },
      [source, page, filters],
    ),
  )
  const groups = new Map<string, Entry[]>()
  for (const item of resource.data?.items ?? [])
    groups.set(item.actor, [...(groups.get(item.actor) ?? []), item])
  const selected = resource.data?.items.find((item) => item.id === selectedId)
  return (
    <>
      <header className="admin-heading">
        <div>
          <h1>Nhật ký thao tác</h1>
          <p>Theo dõi ai đã thao tác, khi nào và kết quả ra sao.</p>
        </div>
        <span className="admin-badge neutral">Chỉ xem</span>
      </header>
      <div className="admin-tabs" aria-label="Nguồn nhật ký">
        {(['control', 'account'] as const).map((s) => (
          <button
            key={s}
            aria-pressed={source === s}
            onClick={() => {
              setSource(s)
              setDraft(initial)
              setFilters(initial)
              setPage(1)
              setSelectedId(null)
              setValidation('')
            }}
          >
            {s === 'control' ? 'Điều khiển trụ' : 'Tài khoản'}
          </button>
        ))}
      </div>
      <form
        className="admin-filters admin-audit-filters"
        onSubmit={(e) => {
          e.preventDefault()
          if (draft.from && draft.to && draft.from > draft.to) {
            setValidation(
              'Thời gian bắt đầu phải trước hoặc bằng thời gian kết thúc.',
            )
            return
          }
          setValidation('')
          setPage(1)
          setSelectedId(null)
          if (JSON.stringify(filters) === JSON.stringify(draft))
            resource.reload()
          else setFilters(draft)
        }}
      >
        <label>
          Người thực hiện
          <input
            type="email"
            maxLength={320}
            placeholder="Email chính xác"
            value={draft.actor}
            onChange={(e) => setDraft({ ...draft, actor: e.target.value })}
          />
        </label>
        {source === 'control' ? (
          <label>
            Trụ
            <input
              maxLength={100}
              placeholder="Mã trụ chính xác"
              value={draft.chargePoint}
              onChange={(e) =>
                setDraft({ ...draft, chargePoint: e.target.value })
              }
            />
          </label>
        ) : (
          <label>
            Thao tác
            <select
              value={draft.action}
              onChange={(e) => setDraft({ ...draft, action: e.target.value })}
            >
              <option value="">Tất cả thao tác</option>
              <option value="account_created">Cấp tài khoản</option>
              <option value="account_updated">Cập nhật tài khoản</option>
            </select>
          </label>
        )}
        <label>
          Từ (giờ Việt Nam)
          <input
            type="datetime-local"
            value={draft.from}
            onChange={(e) => setDraft({ ...draft, from: e.target.value })}
          />
        </label>
        <label>
          Đến (giờ Việt Nam)
          <input
            type="datetime-local"
            value={draft.to}
            onChange={(e) => setDraft({ ...draft, to: e.target.value })}
          />
        </label>
        <button className="admin-primary" disabled={resource.loading}>
          Áp dụng
        </button>
        <button
          type="button"
          onClick={() => {
            setDraft(initial)
            setFilters(initial)
            setPage(1)
            setSelectedId(null)
            setValidation('')
          }}
        >
          Xóa lọc
        </button>
      </form>
      <ErrorNotice
        error={validation || resource.error}
        onRetry={resource.error ? resource.reload : undefined}
      />
      <div className="admin-split admin-audit-split">
        <section
          className="admin-panel admin-audit-groups"
          aria-label="Nhật ký theo người thực hiện"
          aria-busy={resource.loading}
        >
          <div className="admin-panel-title">
            <h2>Nhóm theo người thực hiện</h2>
            <span>Trong trang hiện tại</span>
          </div>
          <div className="admin-scroll">
            {resource.loading && (
              <p className="admin-empty" role="status">
                Đang tải nhật ký…
              </p>
            )}
            {resource.data?.items.length === 0 && (
              <p className="admin-empty">
                Chưa có thao tác phù hợp với bộ lọc này.
              </p>
            )}
            {[...groups].map(([actor, items]) => (
              <section className="admin-actor-group" key={actor}>
                <header>
                  <span className="admin-avatar" aria-hidden="true">
                    {actor.slice(0, 1).toUpperCase()}
                  </span>
                  <strong>{actor}</strong>
                  <span>{items.length} thao tác</span>
                </header>
                {items.map((item) => (
                  <button
                    className={`admin-audit-row ${selectedId === item.id ? 'is-selected' : ''}`}
                    key={item.id}
                    aria-pressed={selectedId === item.id}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <span>
                      <strong>{actionNames[item.action] ?? item.action}</strong>
                      <span>{item.target}</span>
                    </span>
                    <time dateTime={item.time}>{dateTime(item.time)}</time>
                    <span
                      className={`admin-badge ${!item.control || item.control.status === 'Accepted' ? 'good' : 'neutral'}`}
                    >
                      {item.control
                        ? (resultNames[item.control.status] ??
                          item.control.status)
                        : 'Đã lưu'}
                    </span>
                  </button>
                ))}
              </section>
            ))}
          </div>
        </section>
        <aside className="admin-panel admin-detail">
          {selected ? (
            <>
              <h2>Chi tiết thao tác</h2>
              <dl className="admin-facts">
                <dt>Người thực hiện</dt>
                <dd>{selected.actor}</dd>
                <dt>Thời gian</dt>
                <dd>{dateTime(selected.time)}</dd>
                <dt>Thao tác</dt>
                <dd>{actionNames[selected.action] ?? selected.action}</dd>
                <dt>{selected.control ? 'Trụ' : 'Tài khoản'}</dt>
                <dd>{selected.target}</dd>
              </dl>
              <details className="admin-payload">
                <summary>Quyền tại thời điểm thao tác</summary>
                <dl className="admin-facts">
                  <dt>Mã quyền</dt>
                  <dd>{(selected.control ?? selected.account)?.permission ?? 'Bản ghi cũ chưa lưu mã quyền'}</dd>
                  <dt>Vai trò đã được cấp</dt>
                  <dd>{(selected.control ?? selected.account)?.actor_roles?.map(role => roleNames[role as keyof typeof roleNames] ?? role).join(' · ') || 'Bản ghi cũ chưa lưu vai trò'}</dd>
                </dl>
              </details>
              {selected.control ? (
                <>
                  <h3>Kết quả</h3>
                  <p>
                    {resultNames[selected.control.status] ??
                      selected.control.status}
                  </p>
                  {selected.control.status === 'Accepted' && (
                    <p className="admin-muted">
                      Trụ đã chấp nhận lệnh. Điều này chưa xác nhận hành động
                      vật lý đã hoàn tất.
                    </p>
                  )}
                  <dl className="admin-facts">
                    <dt>Phiên sạc</dt>
                    <dd>
                      {selected.control.transaction_id ?? 'Không áp dụng'}
                    </dd>
                    <dt>Nhận phản hồi</dt>
                    <dd>{dateTime(selected.control.received_at)}</dd>
                  </dl>
                  <details className="admin-payload">
                    <summary>Nội dung lệnh</summary>
                    <pre>
                      {JSON.stringify(selected.control.payload, null, 2)}
                    </pre>
                  </details>
                </>
              ) : (
                selected.account && (
                  <>
                    <h3>Trước thay đổi</h3>
                    <StateView state={selected.account.before} />
                    <h3>Sau thay đổi</h3>
                    <StateView state={selected.account.after} />
                    <details className="admin-payload">
                      <summary>Mã bản ghi</summary>
                      <p>ID: {selected.account.id}</p>
                      <p>Tài khoản: {selected.account.target_id}</p>
                    </details>
                  </>
                )
              )}
            </>
          ) : (
            <div className="admin-empty">
              <h2>Chọn một thao tác</h2>
              <p>Xem kết quả và nội dung chi tiết tại đây.</p>
            </div>
          )}
        </aside>
      </div>
      <Pagination
        page={page}
        totalPages={resource.data?.total_pages ?? 1}
        total={resource.data?.total ?? 0}
        busy={resource.loading}
        onPage={(p) => {
          setPage(p)
          setSelectedId(null)
        }}
      />
    </>
  )
}
function StateView({ state }: { state: AccountState | null }) {
  return state ? (
    <dl className="admin-facts">
      <dt>Email</dt>
      <dd>{state.email}</dd>
      <dt>Vai trò</dt>
      <dd>{state.roles.map((r) => roleNames[r] ?? r).join(' · ')}</dd>
      <dt>Trạng thái</dt>
      <dd>{statusNames[state.status] ?? state.status}</dd>
    </dl>
  ) : (
    <p className="admin-muted">Chưa có tài khoản trước thao tác này.</p>
  )
}
