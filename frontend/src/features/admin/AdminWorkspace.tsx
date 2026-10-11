// Direction: Operate; inherit owner World A and the three approved admin compositions.
// Accounts list/detail + collapsible guide; actor-group audit; four real health plots.
import { useEffect, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import type { AuthenticatedUser } from '../auth/model/auth'
import { AdminAccounts } from './AdminAccounts'
import { AdminAudit } from './AdminAudit'
import { AdminHealth } from './AdminHealth'
import { AdminManualTopup } from './AdminManualTopup'
import './admin.css'

type Area = 'accounts' | 'audit' | 'health' | 'topup'
const areas: {
  id: Area
  label: string
  icon: 'settings' | 'session' | 'report'
}[] = [
  { id: 'accounts', label: 'Tài khoản & vai trò', icon: 'settings' },
  { id: 'topup', label: 'Nạp tiền thủ công', icon: 'report' },
  { id: 'audit', label: 'Nhật ký thao tác', icon: 'session' },
  { id: 'health', label: 'Sức khỏe hệ thống', icon: 'report' },
]
const readArea = (): Area =>
  areas.find((a) => window.location.hash === `#admin-${a.id}`)?.id ?? 'accounts'
export function AdminWorkspace({
  currentUser,
  onLogout,
  onExit,
}: {
  currentUser: AuthenticatedUser
  onLogout: () => Promise<void>
  onExit?: () => void
}) {
  const [area, setArea] = useState(readArea)
  const [logoutError, setLogoutError] = useState('')
  const [loggingOut, setLoggingOut] = useState(false)
  useEffect(() => {
    const change = () => setArea(readArea())
    window.addEventListener('hashchange', change)
    return () => window.removeEventListener('hashchange', change)
  }, [])
  if (!currentUser.roles.includes('admin'))
    return <main>Bạn không có quyền truy cập quản trị.</main>
  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-brand">
          <Icon name="bolt" />
          CSMS
        </div>
        <nav aria-label="Quản trị">
          {areas.map((a) => (
            <a
              key={a.id}
              href={`#admin-${a.id}`}
              aria-current={area === a.id ? 'page' : undefined}
              onClick={() => setArea(a.id)}
            >
              <Icon name={a.icon} />
              <span>{a.label}</span>
            </a>
          ))}
        </nav>
        <footer>
          <strong>Quản trị</strong>
          <span title={currentUser.email}>{currentUser.email}</span>
          {onExit && <button onClick={onExit}>Đổi khu vực</button>}
          {logoutError && <p role="alert">{logoutError}</p>}
          <button
            disabled={loggingOut}
            onClick={async () => {
              setLoggingOut(true)
              setLogoutError('')
              try {
                await onLogout()
              } catch {
                setLogoutError('Không đăng xuất được. Hãy thử lại.')
                setLoggingOut(false)
              }
            }}
          >
            <Icon name="logout" />
            {loggingOut ? 'Đang đăng xuất…' : 'Đăng xuất'}
          </button>
        </footer>
      </aside>
      <main className="admin-page" key={area}>
        {area === 'accounts' ? (
          <AdminAccounts currentUser={currentUser} />
        ) : area === 'topup' ? (
          <AdminManualTopup />
        ) : area === 'audit' ? (
          <AdminAudit />
        ) : (
          <AdminHealth />
        )}
      </main>
    </div>
  )
}
