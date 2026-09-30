import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Icon, type IconName } from '../components/icons/Icon'
import type { AuthenticatedUser } from '../features/auth/model/auth'

const navigation: Array<{ label: string; icon: IconName; active?: boolean }> = [
  { label: 'Tổng quan', icon: 'dashboard' },
  { label: 'Trạm sạc', icon: 'station', active: true },
  { label: 'Trụ sạc', icon: 'charger' },
  { label: 'Phiên sạc', icon: 'session' },
  { label: 'Báo cáo', icon: 'report' },
]

interface AppShellProps {
  children: ReactNode
  currentUser: AuthenticatedUser
  onUnavailableNavigation: (label: string) => void
}

const roleLabels: Record<string, string> = {
  driver: 'Tài xế',
  station_owner: 'Chủ trạm',
  operator: 'Vận hành viên',
  accountant: 'Kế toán',
  admin: 'Quản trị viên',
}

export function AppShell({
  children,
  currentUser,
  onUnavailableNavigation,
}: AppShellProps) {
  const [isNavigationOpen, setIsNavigationOpen] = useState(false)
  const sidebarRef = useRef<HTMLElement>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const initials = currentUser.email.slice(0, 2).toUpperCase()
  const roleLabel = roleLabels[currentUser.roles[0] ?? ''] ?? 'Người dùng'

  const closeNavigation = useCallback((restoreFocus = true) => {
    setIsNavigationOpen(false)
    if (restoreFocus) {
      menuButtonRef.current?.focus()
    }
  }, [])

  useEffect(() => {
    const mediaQuery = window.matchMedia?.('(max-width: 680px)')
    if (!mediaQuery) return
    const handleChange = (event: MediaQueryListEvent) => {
      if (!event.matches) setIsNavigationOpen(false)
    }
    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [])

  useEffect(() => {
    if (!isNavigationOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const focusableElements = Array.from(
      sidebarRef.current?.querySelectorAll<HTMLElement>('a[href], button') ?? [],
    )
    focusableElements[0]?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeNavigation()
        return
      }
      if (event.key !== 'Tab' || focusableElements.length === 0) return

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault()
        lastElement.focus()
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [closeNavigation, isNavigationOpen])

  return (
    <div className="app-shell">
      <aside
        ref={sidebarRef}
        className={`sidebar${isNavigationOpen ? ' sidebar--open' : ''}`}
        id="primary-navigation"
      >
        <a className="brand" href="#top" aria-label="CSMS - Trang chủ">
          <span className="brand__mark"><Icon name="bolt" /></span>
          <span>CSMS</span>
        </a>
        <nav aria-label="Điều hướng chính">
          {navigation.map((item) => (
            <a
              key={item.label}
              className={item.active ? 'nav-link nav-link--active' : 'nav-link'}
              aria-label={item.label}
              aria-current={item.active ? 'page' : undefined}
              href={item.active ? '#stations' : `#${item.label.toLowerCase()}`}
              onClick={(event) => {
                if (!item.active) {
                  event.preventDefault()
                  onUnavailableNavigation(item.label)
                }
                closeNavigation()
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
            aria-label="Cài đặt"
            href="#settings"
            onClick={(event) => {
              event.preventDefault()
              closeNavigation()
              onUnavailableNavigation('Cài đặt')
            }}
          >
            <Icon name="settings" />
            <span>Cài đặt</span>
          </a>
          <div className="user-panel">
            <span className="avatar">{initials}</span>
            <div><strong>{roleLabel}</strong><span>{currentUser.email}</span></div>
          </div>
        </div>
      </aside>
      {isNavigationOpen && (
        <div
          className="navigation-backdrop"
          aria-hidden="true"
          onClick={() => closeNavigation()}
        />
      )}

      <main className="main-content" id="top">
        <header className="topbar">
          <button
            ref={menuButtonRef}
            className="menu-button"
            type="button"
            aria-label={isNavigationOpen ? 'Đóng điều hướng' : 'Mở điều hướng'}
            aria-controls="primary-navigation"
            aria-expanded={isNavigationOpen}
            onClick={() => {
              if (isNavigationOpen) closeNavigation()
              else setIsNavigationOpen(true)
            }}
          >
            <Icon name={isNavigationOpen ? 'close' : 'menu'} />
          </button>
          <div className="mobile-brand">
            <span className="brand__mark"><Icon name="bolt" /></span>
            <strong>CSMS</strong>
          </div>
          <div className="system-state">Cổng quản lý CSMS</div>
          <button
            className="avatar avatar--button"
            type="button"
            aria-label="Mở tài khoản"
            onClick={() => onUnavailableNavigation('Tài khoản')}
          >
            {initials}
          </button>
        </header>
        {children}
      </main>
    </div>
  )
}
