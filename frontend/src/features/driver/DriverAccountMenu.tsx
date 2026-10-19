import { useEffect, useId, useRef } from 'react'
import { Icon } from '../../components/icons/Icon'

export function DriverAccountMenu({ email, open, onOpenChange, onNavigate, onLogout, loggingOut, logoutError }: {
  email: string; open: boolean; onOpenChange: (open: boolean) => void
  onNavigate: (area: 'reservations' | 'privacy' | 'history') => void; onLogout: () => void; loggingOut: boolean; logoutError: string
}) {
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null)
  const id = useId()
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (event.target instanceof Node && !root.current?.contains(event.target)) onOpenChange(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { onOpenChange(false); trigger.current?.focus({ preventScroll: true }) } }
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [open, onOpenChange])
  return <div ref={root} className="driver-account-control">
    <button ref={trigger} type="button" className="secondary-button driver-account-trigger" aria-label="Tài khoản" aria-expanded={open} aria-controls={id} onClick={() => onOpenChange(!open)}><Icon name="menu" /><span>Tài khoản</span></button>
    {open && <nav id={id} className="driver-account-dropdown" aria-label="Tùy chọn tài khoản">
      <span className="driver-account-email" title={email}>{email}</span>
      <button type="button" onClick={() => onNavigate('history')}><Icon name="session" />Lịch sử phiên sạc</button>
      <button type="button" onClick={() => onNavigate('reservations')}><Icon name="calendar" />Lịch sử đặt chỗ</button>
      <button type="button" onClick={() => onNavigate('privacy')}><Icon name="settings" />Dữ liệu cá nhân</button>
      <button type="button" disabled={loggingOut} onClick={onLogout}><Icon name="logout" />{loggingOut ? 'Đang đăng xuất…' : 'Đăng xuất'}</button>
      {logoutError && <p role="alert">{logoutError}</p>}
    </nav>}
  </div>
}
