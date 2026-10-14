import { useEffect, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import type { AuthenticatedUser } from '../auth/model/auth'
import { FinancePage } from './FinancePage'
import './accountant.css'

type Area = 'sessions' | 'invoices' | 'reconciliation'
const areas: {
  id: Area
  label: string
  icon: 'session' | 'report' | 'settings'
}[] = [
  { id: 'sessions', label: 'Phiên sạc & thanh toán', icon: 'session' },
  { id: 'invoices', label: 'Hóa đơn phí sạc', icon: 'report' },
  { id: 'reconciliation', label: 'Cần đối chiếu', icon: 'settings' },
]

const readArea = (): Area =>
  areas.find((a) => window.location.hash.split('?')[0] === `#accountant-${a.id}`)?.id ?? 'sessions'

export function AccountantWorkspace({
  currentUser,
  onLogout,
  onExit,
}: {
  currentUser: AuthenticatedUser
  onLogout: () => Promise<void>
  onExit?: () => void
}) {
  const [area, setArea] = useState(readArea)
  const [accountOpen, setAccountOpen] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  const [loggingOut, setLoggingOut] = useState(false)

  useEffect(() => {
    const change = () => setArea(readArea())
    window.addEventListener('hashchange', change)
    return () => window.removeEventListener('hashchange', change)
  }, [])

  if (!currentUser.roles.includes('accountant'))
    return <main>Bạn không có quyền truy cập khu vực kế toán.</main>

  return (
    <div className="accountant-shell">
      <aside className="accountant-sidebar">
        <div className="accountant-brand">
          <Icon name="bolt" />
          Kế Toán
        </div>
        <nav aria-label="Kế toán">
          {areas.map((a) => (
            <a
              key={a.id}
              href={`#accountant-${a.id}`}
              aria-current={area === a.id ? 'page' : undefined}
              onClick={() => setArea(a.id)}
            >
              <Icon name={a.icon} />
              <span>{a.label}</span>
            </a>
          ))}
        </nav>
        <footer>
          <button className="accountant-account-toggle" aria-expanded={accountOpen} aria-controls="accountant-account" onClick={() => setAccountOpen(!accountOpen)}>Tài khoản</button>
          <div id="accountant-account" className={`accountant-account-body ${accountOpen ? 'is-open' : ''}`}>
          <strong>Kế toán</strong>
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
        </div>
        </footer>
      </aside>
      <main className="accountant-page" key={area}>
        <FinancePage area={area}/>
      </main>
    </div>
  )
}
