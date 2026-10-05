import { useCallback, useEffect, useState } from 'react'
import type { AuthenticatedUser } from '../auth/model/auth'
import {
  adminRequest,
  AdminApiError,
  dateTime,
  queryString,
  roleNames,
  statusNames,
  writeJson,
  type Account,
  type Page,
  type Role,
  type RoleCode,
} from './adminApi'
import { ErrorNotice, Pagination } from './AdminShared'
import { useResource } from './useResource'

export function AdminAccounts({
  currentUser,
}: {
  currentUser: AuthenticatedUser
}) {
  const [filters, setFilters] = useState({
    search: '',
    role: '',
    status: '',
    page: 1,
  })
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [notice, setNotice] = useState('')
  const roles = useResource(
    useCallback(
      (signal) => adminRequest<Role[]>('/admin/roles', { signal }),
      [],
    ),
  )
  const accounts = useResource(
    useCallback(
      (signal) =>
        adminRequest<Page<Account>>(
          `/admin/accounts?${queryString({ ...filters, page_size: 20 })}`,
          { signal },
        ),
      [filters],
    ),
  )
  useEffect(() => {
    const timer = setTimeout(
      () =>
        setFilters((f) =>
          f.search === search.trim()
            ? f
            : { ...f, search: search.trim(), page: 1 },
        ),
      300,
    )
    return () => clearTimeout(timer)
  }, [search])
  const [guideOpen, setGuideOpen] = useState(() => {
    try {
      return localStorage.getItem('csms-admin-guide-open') !== 'false'
    } catch {
      return true
    }
  })
  const saved = (account: Account, message: string) => {
    setCreating(false)
    setSelectedId(account.id)
    setNotice(message)
    accounts.reload()
  }
  return (
    <>
      <header className="admin-heading">
        <div>
          <h1>{creating ? 'Cấp tài khoản mới' : 'Tài khoản & vai trò'}</h1>
          <p>
            {creating
              ? 'Ba bước để cấp đúng quyền cho thành viên.'
              : 'Cấp quyền phù hợp, quản lý truy cập của thành viên.'}
          </p>
        </div>
        {creating ? (
          <button onClick={() => setCreating(false)}>Hủy</button>
        ) : (
          <button
            className="admin-primary"
            disabled={!roles.data}
            onClick={() => {
              setNotice('')
              setCreating(true)
            }}
          >
            Cấp tài khoản
          </button>
        )}
      </header>
      <ErrorNotice error={roles.error} onRetry={roles.reload} />
      {notice && (
        <div className="admin-success" role="status">
          {notice}
          <button aria-label="Đóng thông báo" onClick={() => setNotice('')}>
            Đóng
          </button>
        </div>
      )}
      {creating ? (
        roles.data && (
          <AccountWizard
            roles={roles.data}
            onSaved={(a) =>
              saved(
                a,
                'Đã cấp tài khoản. Thành viên có thể đăng nhập bằng thông tin vừa cấp.',
              )
            }
          />
        )
      ) : (
        <>
          <details
            className="admin-guide"
            open={guideOpen}
            onToggle={(event) => {
              const open = event.currentTarget.open
              setGuideOpen(open)
              try {
                localStorage.setItem('csms-admin-guide-open', String(open))
              } catch {
                /* Storage is optional. */
              }
            }}
          >
            <summary>
              Bắt đầu trong 3 bước <span>Có thể thu gọn khi đã quen</span>
            </summary>
            <ol>
              <li>
                <strong>Cấp tài khoản</strong>
                <span>Nhập email và mật khẩu ban đầu.</span>
              </li>
              <li>
                <strong>Chọn vai trò</strong>
                <span>Chỉ cấp quyền cần cho công việc.</span>
              </li>
              <li>
                <strong>Kiểm tra & hoàn tất</strong>
                <span>Thông báo thông tin đăng nhập cho thành viên.</span>
              </li>
            </ol>
          </details>
          <div className="admin-filters">
            <label>
              Tìm tài khoản
              <input
                type="search"
                value={search}
                maxLength={320}
                placeholder="Email thành viên"
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <label>
              Vai trò
              <select
                value={filters.role}
                onChange={(e) => {
                  setSelectedId(null)
                  setFilters({ ...filters, role: e.target.value, page: 1 })
                }}
              >
                <option value="">Tất cả vai trò</option>
                {roles.data?.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Trạng thái
              <select
                value={filters.status}
                onChange={(e) => {
                  setSelectedId(null)
                  setFilters({ ...filters, status: e.target.value, page: 1 })
                }}
              >
                <option value="">Tất cả trạng thái</option>
                {Object.entries(statusNames).map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <button onClick={accounts.reload} disabled={accounts.loading}>
              Làm mới
            </button>
          </div>
          <ErrorNotice error={accounts.error} onRetry={accounts.reload} />
          <div className="admin-split">
            <section
              className="admin-panel admin-account-list"
              aria-label="Danh sách tài khoản"
              aria-busy={accounts.loading}
            >
              <div className="admin-panel-title">
                <h2>Thành viên</h2>
                <span>
                  {accounts.data
                    ? `${accounts.data.total} tài khoản`
                    : 'Đang tải…'}
                </span>
              </div>
              <div className="admin-scroll">
                {accounts.loading && (
                  <p className="admin-empty" role="status">
                    Đang tải tài khoản…
                  </p>
                )}
                {accounts.data?.items.length === 0 && (
                  <p className="admin-empty">
                    Không tìm thấy tài khoản phù hợp. Hãy đổi bộ lọc hoặc cấp
                    tài khoản mới.
                  </p>
                )}
                {accounts.data?.items.map((a) => (
                  <button
                    key={a.id}
                    className={`admin-account-row ${selectedId === a.id ? 'is-selected' : ''}`}
                    aria-pressed={selectedId === a.id}
                    onClick={() => setSelectedId(a.id)}
                  >
                    <span className="admin-avatar" aria-hidden="true">
                      {a.email.slice(0, 1).toUpperCase()}
                    </span>
                    <span className="admin-account-name">
                      <strong>{a.email}</strong>
                      <span>
                        {a.roles.map((r) => roleNames[r] ?? r).join(' · ')}
                      </span>
                    </span>
                    <span
                      className={`admin-badge ${a.status === 'active' ? 'good' : 'neutral'}`}
                    >
                      {statusNames[a.status] ?? a.status}
                    </span>
                  </button>
                ))}
              </div>
            </section>
            <aside className="admin-panel admin-detail">
              {selectedId ? (
                <AccountDetail
                  key={selectedId}
                  id={selectedId}
                  currentUser={currentUser}
                  roles={roles.data ?? []}
                  onSaved={(a) => saved(a, 'Đã lưu thay đổi tài khoản.')}
                />
              ) : (
                <div className="admin-empty">
                  <h2>Chọn một tài khoản</h2>
                  <p>Xem quyền truy cập và quản lý trạng thái tại đây.</p>
                </div>
              )}
            </aside>
          </div>
          <Pagination
            page={filters.page}
            totalPages={accounts.data?.total_pages ?? 1}
            total={accounts.data?.total ?? 0}
            busy={accounts.loading}
            onPage={(page) => {
              setSelectedId(null)
              setFilters({ ...filters, page })
            }}
          />
        </>
      )}
    </>
  )
}

function RoleChoices({
  roles,
  selected,
  onChange,
  disabled,
  self,
}: {
  roles: Role[]
  selected: RoleCode[]
  onChange: (roles: RoleCode[]) => void
  disabled?: boolean
  self?: boolean
}) {
  return (
    <fieldset className="admin-role-choices" disabled={disabled}>
      <legend>Vai trò được cấp</legend>
      {roles.map((r) => (
        <label key={r.code}>
          <input
            type="checkbox"
            checked={selected.includes(r.code)}
            disabled={self && r.code === 'admin'}
            onChange={(e) =>
              onChange(
                e.target.checked
                  ? [...selected, r.code]
                  : selected.filter((code) => code !== r.code),
              )
            }
          />
          <span>{r.name}</span>
        </label>
      ))}
    </fieldset>
  )
}
function AccountWizard({
  roles,
  onSaved,
}: {
  roles: Role[]
  onSaved: (a: Account) => void
}) {
  const [step, setStep] = useState(1)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [visible, setVisible] = useState(false)
  const [selected, setSelected] = useState<RoleCode[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  return (
    <>
      <ol className="admin-steps" aria-label="Các bước cấp tài khoản">
        {['Thông tin đăng nhập', 'Vai trò', 'Kiểm tra & cấp'].map((name, i) => (
          <li key={name} aria-current={step === i + 1 ? 'step' : undefined}>
            <span>{i + 1}</span>
            {name}
          </li>
        ))}
      </ol>
      <form
        className="admin-panel admin-wizard"
        onSubmit={async (e) => {
          e.preventDefault()
          setError(undefined)
          if (step === 2 && !selected.length) {
            setError('Hãy chọn ít nhất một vai trò.')
            return
          }
          if (step < 3) {
            setStep(step + 1)
            return
          }
          setBusy(true)
          try {
            const a = await adminRequest<Account>(
              '/admin/accounts',
              writeJson('POST', {
                email: email.trim(),
                password,
                roles: selected,
              }),
            )
            setPassword('')
            onSaved(a)
          } catch (err) {
            setError(err)
          } finally {
            setBusy(false)
          }
        }}
      >
        <ErrorNotice error={error} />
        <div className="admin-scroll">
          {step === 1 ? (
            <div className="admin-form-columns">
              <div>
                <h2>Thông tin đăng nhập</h2>
                <label>
                  Email thành viên
                  <input
                    type="email"
                    required
                    maxLength={320}
                    autoComplete="off"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </label>
                <label>
                  Mật khẩu ban đầu
                  <div className="admin-password">
                    <input
                      type={visible ? 'text' : 'password'}
                      aria-label="Mật khẩu ban đầu"
                      required
                      minLength={12}
                      maxLength={1024}
                      autoComplete="new-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                    <button type="button" onClick={() => setVisible(!visible)}>
                      {visible ? 'Ẩn' : 'Hiện'}
                    </button>
                  </div>
                </label>
                <p className="admin-muted">
                  Ít nhất 12 ký tự. Gửi mật khẩu qua kênh riêng cho thành viên
                  sau khi cấp.
                </p>
              </div>
              <div className="admin-explanation">
                <h2>Mỗi thành viên, một tài khoản</h2>
                <p>Thành viên dùng email và mật khẩu này để đăng nhập CSMS.</p>
                <p>
                  Ở bước tiếp theo, chọn một hoặc nhiều vai trò phù hợp với công
                  việc.
                </p>
              </div>
            </div>
          ) : step === 2 ? (
            <>
              <h2>Chọn quyền truy cập</h2>
              <p className="admin-muted">
                Một tài khoản có thể đảm nhận nhiều vai trò.
              </p>
              <RoleChoices
                roles={roles}
                selected={selected}
                onChange={setSelected}
              />
            </>
          ) : (
            <>
              <h2>Kiểm tra trước khi cấp</h2>
              <dl className="admin-facts">
                <dt>Email</dt>
                <dd>{email.trim()}</dd>
                <dt>Vai trò</dt>
                <dd>{selected.map((r) => roleNames[r]).join(' · ')}</dd>
                <dt>Trạng thái</dt>
                <dd>Hoạt động</dd>
                <dt>Mật khẩu</dt>
                <dd>Đã nhập · không hiển thị tại bước kiểm tra</dd>
              </dl>
              <p>
                Tài khoản được cấp có thể đăng nhập ngay với các vai trò trên.
              </p>
            </>
          )}
        </div>
        <footer className="admin-form-footer">
          <span>Bước {step} / 3</span>
          <div className="admin-actions">
            {step > 1 && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setError(undefined)
                  setStep(step - 1)
                }}
              >
                Quay lại
              </button>
            )}
            <button className="admin-primary" disabled={busy} type="submit">
              {busy ? 'Đang cấp…' : step === 3 ? 'Cấp tài khoản' : 'Tiếp tục'}
            </button>
          </div>
        </footer>
      </form>
    </>
  )
}

function AccountDetail({
  id,
  currentUser,
  roles,
  onSaved,
}: {
  id: string
  currentUser: AuthenticatedUser
  roles: Role[]
  onSaved: (a: Account) => void
}) {
  const detail = useResource(
    useCallback(
      (signal) => adminRequest<Account>(`/admin/accounts/${id}`, { signal }),
      [id],
    ),
  )
  const [editing, setEditing] = useState(false)
  const [selected, setSelected] = useState<RoleCode[]>([])
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const [savedAccount, setSavedAccount] = useState<Account>()
  const a = savedAccount ?? detail.data
  const self = id === currentUser.id
  const mutable = a?.status === 'active' || a?.status === 'suspended'
  async function save(changes: { roles?: RoleCode[]; status?: string }) {
    if (!a) return
    setBusy(true)
    setError(undefined)
    try {
      const result = await adminRequest<Account>(
        `/admin/accounts/${id}`,
        writeJson('PATCH', { expected_updated_at: a.updated_at, ...changes }),
      )
      setSavedAccount(result)
      setEditing(false)
      setConfirming(false)
      onSaved(result)
    } catch (err) {
      setError(err)
      if (err instanceof AdminApiError && err.status === 409) {
        setSavedAccount(undefined)
        setEditing(false)
        setConfirming(false)
        detail.reload()
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <ErrorNotice error={detail.error} onRetry={detail.reload} />
      <ErrorNotice error={error} />
      {detail.loading ? (
        <p role="status">Đang tải thông tin…</p>
      ) : (
        a && (
          <>
            <h2>Thông tin tài khoản</h2>
            <strong className="admin-email">{a.email}</strong>
            <span
              className={`admin-badge ${a.status === 'active' ? 'good' : 'neutral'}`}
            >
              {statusNames[a.status] ?? a.status}
            </span>
            <dl className="admin-facts">
              <dt>Tạo lúc</dt>
              <dd>{dateTime(a.created_at)}</dd>
              <dt>Cập nhật</dt>
              <dd>{dateTime(a.updated_at)}</dd>
            </dl>
            {editing ? (
              <>
                <RoleChoices
                  roles={roles}
                  selected={selected}
                  onChange={setSelected}
                  disabled={busy}
                  self={self}
                />
                <div className="admin-actions">
                  <button disabled={busy} onClick={() => setEditing(false)}>
                    Hủy
                  </button>
                  <button
                    className="admin-primary"
                    disabled={
                      busy ||
                      !selected.length ||
                      selected.slice().sort().join() ===
                        a.roles.slice().sort().join()
                    }
                    onClick={() => save({ roles: selected })}
                  >
                    {busy ? 'Đang lưu…' : 'Lưu vai trò'}
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3>Quyền truy cập</h3>
                <div className="admin-tags">
                  {a.roles.map((r) => (
                    <span className="admin-badge neutral" key={r}>
                      {roleNames[r] ?? r}
                    </span>
                  ))}
                </div>
                {mutable && roles.length > 0 && (
                  <button
                    disabled={busy || confirming}
                    onClick={() => {
                      setError(undefined)
                      setSelected(a.roles)
                      setEditing(true)
                    }}
                  >
                    Sửa vai trò
                  </button>
                )}
              </>
            )}
            {self ? (
              <p className="admin-muted">
                Bạn không thể tự khóa tài khoản hoặc bỏ quyền quản trị của mình.
              </p>
            ) : (
              mutable &&
              !editing && (
                <div className="admin-account-access">
                  {confirming ? (
                    <>
                      <h3>
                        {a.status === 'active'
                          ? 'Khóa tài khoản này?'
                          : 'Mở khóa tài khoản này?'}
                      </h3>
                      <p>
                        {a.status === 'active'
                          ? 'Các phiên đăng nhập hiện tại sẽ bị thu hồi. Thành viên không thể đăng nhập khi bị khóa.'
                          : 'Thành viên cần đăng nhập lại để tiếp tục sử dụng.'}
                      </p>
                      <div className="admin-actions">
                        <button
                          disabled={busy}
                          onClick={() => setConfirming(false)}
                        >
                          Hủy
                        </button>
                        <button
                          className={
                            a.status === 'active'
                              ? 'admin-danger'
                              : 'admin-primary'
                          }
                          disabled={busy}
                          onClick={() =>
                            save({
                              status:
                                a.status === 'active' ? 'suspended' : 'active',
                            })
                          }
                        >
                          {busy ? 'Đang lưu…' : 'Xác nhận'}
                        </button>
                      </div>
                    </>
                  ) : (
                    <button
                      disabled={busy}
                      className={a.status === 'active' ? 'admin-danger' : ''}
                      onClick={() => {
                        setError(undefined)
                        setConfirming(true)
                      }}
                    >
                      {a.status === 'active'
                        ? 'Khóa tài khoản'
                        : 'Mở khóa tài khoản'}
                    </button>
                  )}
                </div>
              )
            )}
            {!mutable && (
              <p className="admin-muted">
                Trạng thái này chỉ cho phép xem thông tin.
              </p>
            )}
          </>
        )
      )}
    </>
  )
}
