import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Icon, type IconName } from '../components/icons/Icon'
import type { AuthenticatedUser } from '../features/auth/model/auth'
import { getHomeRole, getPermissions } from '../features/auth/model/permissions'

const roleNavigation: Record<string, { label: string; icon: IconName }> = {
  driver: { label: 'Khu vực tài xế', icon: 'session' },
  accountant: { label: 'Khu vực kế toán', icon: 'report' },
}

interface AppShellProps {
  children: ReactNode
  currentUser: AuthenticatedUser
  onLogout: () => Promise<void>
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
  onLogout,
}: AppShellProps) {
  const [isNavigationOpen, setIsNavigationOpen] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  const sidebarRef = useRef<HTMLElement>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const initials = currentUser.email.slice(0, 2).toUpperCase()
  const homeRole = getHomeRole(currentUser)
  const roleLabel = roleLabels[homeRole] ?? 'Người dùng'
  const navigationItem = getPermissions(currentUser).canViewStations
    ? { label: 'Trạm sạc', icon: 'station' as IconName }
    : roleNavigation[homeRole]

  const closeNavigation = useCallback((restoreFocus = true) => {
    setIsNavigationOpen(false)
    if (restoreFocus) {
      menuButtonRef.current?.focus()
    }
  }, [])

  const handleLogout = async () => {
    if (isLoggingOut) return
    setIsLoggingOut(true)
    setLogoutError('')
    try {
      await onLogout()
    } catch {
      setLogoutError('Không thể đăng xuất. Vui lòng kiểm tra kết nối và thử lại.')
      setIsLoggingOut(false)
    }
  }

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
          {(navigationItem ? [navigationItem] : []).map((item) => (
            <a
              key={item.label}
              className="nav-link nav-link--active"
              aria-label={item.label}
              aria-current="page"
              href="#stations"
              onClick={() => closeNavigation()}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="sidebar__footer">
          <div className="user-panel">
            <span className="avatar">{initials}</span>
            <div>
              <strong>{roleLabel}</strong>
              <span className="user-panel__email" title={currentUser.email}>
                {currentUser.email}
              </span>
            </div>
          </div>
          {logoutError && (
            <p className="logout-error" role="alert">{logoutError}</p>
          )}
          <button
            className="logout-button"
            type="button"
            disabled={isLoggingOut}
            onClick={handleLogout}
          >
            <Icon name="logout" />
            <span>{isLoggingOut ? 'Đang đăng xuất…' : 'Đăng xuất'}</span>
          </button>
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
          <span className="avatar" aria-label={`Tài khoản ${currentUser.email}`}>
            {initials}
          </span>
        </header>
        {children}
      </main>
    </div>
  )
}
