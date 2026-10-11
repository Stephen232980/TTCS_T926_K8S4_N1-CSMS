import { useEffect, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import type { AuthenticatedUser } from '../auth/model/auth'
import { ChargingSessionsPage } from '../charging/ChargingSessionsPage'
import './accountant.css'

type Area = 'sessions' | 'invoices' | 'reconciliation'
const areas: {
  id: Area
  label: string
  icon: 'session' | 'report' | 'settings'
}[] = [
  { id: 'sessions', label: 'Phiên sạc & Doanh thu', icon: 'session' },
  { id: 'invoices', label: 'Hoá đơn điện tử', icon: 'report' },
  { id: 'reconciliation', label: 'Đối soát đối tác', icon: 'settings' },
]

const readArea = (): Area =>
  areas.find((a) => window.location.hash === `#accountant-${a.id}`)?.id ?? 'sessions'

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
        </footer>
      </aside>
      <main className="accountant-page" key={area}>
        {area === 'sessions' ? (
          <ChargingSessionsPage area="accounting" canManage={false} canClose={false} />
        ) : area === 'invoices' ? (
          <AccountantInvoices />
        ) : (
          <AccountantReconciliation />
        )}
      </main>
    </div>
  )
}

function AccountantInvoices() {
  return (
    <section className="accountant-panel" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <header className="accountant-heading" style={{ padding: '24px 24px 16px' }}>
        <div>
          <h1>Hoá đơn điện tử</h1>
          <p>Quản lý và xuất hoá đơn cho các phiên sạc.</p>
        </div>
        <div className="accountant-actions">
          <button className="accountant-primary">Xuất hoá đơn mới</button>
        </div>
      </header>
      <div className="accountant-empty" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <h2>Chưa có hoá đơn nào</h2>
        <p>Tính năng xuất và quản lý hoá đơn điện tử đang được hoàn thiện.</p>
      </div>
    </section>
  )
}

function AccountantReconciliation() {
  return (
    <section className="accountant-panel" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <header className="accountant-heading" style={{ padding: '24px 24px 16px' }}>
        <div>
          <h1>Đối soát đối tác</h1>
          <p>Đối soát thanh toán với cổng thanh toán và chủ trạm.</p>
        </div>
        <div className="accountant-actions">
          <button className="accountant-primary">Tạo kỳ đối soát</button>
        </div>
      </header>
      <div className="accountant-empty" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <h2>Không có dữ liệu đối soát</h2>
        <p>Tính năng đối soát thanh toán đang được hoàn thiện.</p>
      </div>
    </section>
  )
}
