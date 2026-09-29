import type { ReactNode } from 'react'
import { Icon, type IconName } from '../components/icons/Icon'

const navigation: Array<{ label: string; icon: IconName; active?: boolean }> = [
  { label: 'Tổng quan', icon: 'dashboard' },
  { label: 'Trạm sạc', icon: 'station', active: true },
  { label: 'Trụ sạc', icon: 'charger' },
  { label: 'Phiên sạc', icon: 'session' },
  { label: 'Báo cáo', icon: 'report' },
]

interface AppShellProps {
  children: ReactNode
  onUnavailableNavigation: (label: string) => void
}

export function AppShell({
  children,
  onUnavailableNavigation,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="CSMS - Trang chủ">
          <span className="brand__mark"><Icon name="bolt" /></span>
          <span>CSMS</span>
        </a>
        <nav aria-label="Điều hướng chính">
          {navigation.map((item) => (
            <a
              key={item.label}
              className={item.active ? 'nav-link nav-link--active' : 'nav-link'}
              href={item.active ? '#stations' : `#${item.label.toLowerCase()}`}
              onClick={(event) => {
                if (!item.active) {
                  event.preventDefault()
                  onUnavailableNavigation(item.label)
                }
              }}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="sidebar__footer">
          <a
            className="nav-link"
            href="#settings"
            onClick={(event) => event.preventDefault()}
          >
            <Icon name="settings" />
            <span>Cài đặt</span>
          </a>
          <div className="user-panel">
            <span className="avatar">CT</span>
            <div><strong>Chủ trạm</strong><span>Phiên bản mock</span></div>
          </div>
        </div>
      </aside>

      <main className="main-content" id="top">
        <header className="topbar">
          <div className="mobile-brand">
            <span className="brand__mark"><Icon name="bolt" /></span>
            <strong>CSMS</strong>
          </div>
          <div className="system-state"><span /> Hệ thống ổn định</div>
          <button
            className="avatar avatar--button"
            type="button"
            aria-label="Mở tài khoản"
          >
            CT
          </button>
        </header>
        {children}
      </main>
    </div>
  )
}
