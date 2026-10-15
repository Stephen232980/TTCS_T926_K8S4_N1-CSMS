import { useEffect, useId, useRef, useState } from 'react'
import { notifySessionUnauthorized } from '../auth/sessionEvents'
import { adminRequest, AdminApiError, writeJson, type Account } from './adminApi'
import { ErrorNotice } from './AdminShared'

export function AccountPasswordForm({ account, self, onSaved, onCancel, onConflict }: {
  account: Account
  self: boolean
  onSaved: (account: Account) => void
  onCancel: () => void
  onConflict: () => void
}) {
  const [password, setPassword] = useState('')
  const hintId = useId()
  const [visible, setVisible] = useState(false)
  const [confirm, setConfirm] = useState('')
  const [review, setReview] = useState(false)
  const [validation, setValidation] = useState('')
  const [error, setError] = useState<unknown>()
  const [busy, setBusy] = useState(false)
  const sending = useRef(false)
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])

  async function save() {
    if (sending.current) return
    sending.current = true
    setBusy(true)
    setError(undefined)
    try {
      const result = await adminRequest<Account>(`/admin/accounts/${account.id}/password`, writeJson('POST', {
        expected_updated_at: account.updated_at, password, confirm_password: confirm,
      }))
      if (!active.current) return
      setPassword(''); setConfirm('')
      setReview(false)
      onSaved(result)
      if (self) notifySessionUnauthorized()
    } catch (cause) {
      if (!active.current) return
      setPassword(''); setConfirm(''); setReview(false)
      setError(cause)
      if (cause instanceof AdminApiError && cause.status === 409) onConflict()
    } finally { sending.current = false; if (active.current) setBusy(false) }
  }

  return <section className="admin-reset-password" aria-label="Đổi mật khẩu tài khoản">
    <h3>Đổi mật khẩu</h3>
    <ErrorNotice error={error} />
    {review ? <>
      <p>Đặt mật khẩu mới cho tài khoản:</p>
      <strong className="admin-email">{account.email}</strong>
      <p>Các phiên đăng nhập hiện tại của tài khoản này sẽ bị thu hồi. Vai trò và trạng thái tài khoản được giữ nguyên.</p>
      {self && <p>Bạn đang đổi mật khẩu của mình và sẽ cần đăng nhập lại.</p>}
      <div className="admin-actions">
        <button disabled={busy} onClick={() => setReview(false)}>Quay lại</button>
        <button className="admin-primary" disabled={busy} onClick={() => void save()}>{busy ? 'Đang đổi…' : 'Xác nhận đổi mật khẩu'}</button>
      </div>
    </> : <form onSubmit={event => {
      event.preventDefault()
      setError(undefined)
      if (password.length < 12 || password.length > 1024) { setValidation('Mật khẩu cần từ 12 đến 1024 ký tự.'); return }
      if (password !== confirm) { setValidation('Mật khẩu nhập lại không khớp.'); return }
      setValidation(''); setReview(true)
    }}>
      <p id={hintId} className="admin-muted">Mật khẩu cần từ 12 đến 1024 ký tự. Khi xác nhận đổi, các phiên đăng nhập của tài khoản này sẽ kết thúc.</p>
      <label>Mật khẩu mới<input type={visible ? 'text' : 'password'} aria-describedby={hintId} autoComplete="new-password" minLength={12} maxLength={1024} required value={password} onChange={event => { setPassword(event.target.value); setValidation('') }} /></label>
      <label>Nhập lại mật khẩu mới<input type={visible ? 'text' : 'password'} aria-describedby={hintId} autoComplete="new-password" minLength={12} maxLength={1024} required value={confirm} onChange={event => { setConfirm(event.target.value); setValidation('') }} /></label>
      <button type="button" aria-pressed={visible} onClick={() => setVisible(value => !value)}>{visible ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}</button>
      {validation && <p className="admin-error" role="alert">{validation}</p>}
      <div className="admin-actions"><button type="button" onClick={onCancel}>Hủy đổi mật khẩu</button><button className="admin-primary" type="submit">Xác nhận</button></div>
    </form>}
  </section>
}
