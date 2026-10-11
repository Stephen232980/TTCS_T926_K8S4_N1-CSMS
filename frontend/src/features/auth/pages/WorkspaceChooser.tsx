import { useState } from 'react'
import { Icon, type IconName } from '../../../components/icons/Icon'
import { AuthApiError, type AuthApi } from '../api/authApi'
import { notifySessionUnauthorized } from '../sessionEvents'
import type { AuthenticatedUser } from '../model/auth'
import './workspaceChooser.css'

const areas: Record<string, { name: string; description: string; icon: IconName }> = {
  admin: { name: 'Quản trị', description: 'Tài khoản, nhật ký và sức khỏe toàn hệ thống.', icon: 'settings' },
  station_owner: { name: 'Chủ trạm', description: 'Quản lý các trạm thuộc sở hữu của bạn.', icon: 'station' },
  operator: { name: 'Vận hành', description: 'Theo dõi trụ và xử lý phiên sạc toàn hệ thống.', icon: 'charger' },
  accountant: { name: 'Kế toán', description: 'Xem phiên sạc phục vụ kiểm tra và đối soát.', icon: 'report' },
  driver: { name: 'Tài xế', description: 'Tìm trạm và sử dụng dịch vụ sạc.', icon: 'bolt' },
}

export function WorkspaceChooser({ user, api, onChoose, onLogout }: {
  user: AuthenticatedUser; api: AuthApi
  onChoose: (role: string, updated?: AuthenticatedUser) => void
  onLogout: () => Promise<void>
}) {
  const [remember, setRemember] = useState(!user.defaultRole)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function choose(role: string) {
    if (busy) return
    setBusy(true); setError('')
    try {
      let updated: AuthenticatedUser | undefined
      if (remember) {
        if (!api.setDefaultRole) throw new Error('Không thể lưu khu vực mặc định. Hãy bỏ chọn ghi nhớ để tiếp tục.')
        updated = await api.setDefaultRole(role)
      } else updated = await api.getCurrentUser()
      if (!updated.roles.includes(role)) throw new Error('Vai trò này đã thay đổi. Hãy đăng nhập lại để cập nhật quyền.')
      onChoose(role, updated)
    } catch (err) {
      if (err instanceof AuthApiError && err.status === 401) notifySessionUnauthorized()
      setError(err instanceof Error && !err.message.startsWith('Auth API') ? err.message : 'Không thể mở khu vực. Hãy kiểm tra phiên đăng nhập và thử lại.')
    } finally { setBusy(false) }
  }
  return <main className="workspace-chooser">
    <section aria-labelledby="area-heading">
      <header><strong><Icon name="bolt" /> CSMS</strong><button disabled={busy} onClick={() => { void onLogout().catch(() => setError('Không thể đăng xuất. Hãy thử lại.')) }}>Đăng xuất</button></header>
      <h1 id="area-heading">Bạn muốn làm việc ở khu vực nào?</h1>
      <p>{user.email}</p>
      <div className="workspace-chooser__areas">{user.roles.filter(role => areas[role]).map(role => <button key={role} disabled={busy} onClick={() => void choose(role)}>
        <span aria-hidden="true"><Icon name={areas[role].icon} /></span><strong>{areas[role].name}</strong><small>{areas[role].description}</small>
        {user.defaultRole === role && <em>Mặc định</em>}
      </button>)}</div>
      <label><input type="checkbox" checked={remember} disabled={busy} onChange={event => setRemember(event.target.checked)} /> Mở khu vực đã chọn trong lần đăng nhập sau</label>
      <p className="workspace-chooser__hint">Bạn có thể đổi khu vực bất cứ lúc nào. Mỗi khu vực có phạm vi dữ liệu và thao tác riêng.</p>
      {busy && <p role="status">Đang mở khu vực…</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  </main>
}
