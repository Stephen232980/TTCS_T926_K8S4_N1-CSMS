import { useEffect, useRef } from 'react'
import { Icon } from '../../components/icons/Icon'

import type { DriverNotificationItem } from './driverNotificationService'

export function DriverNotificationToastContainer({
  notifications,
  onDismiss,
}: {
  notifications: DriverNotificationItem[]
  onDismiss: (id: string) => void
}) {
  if (notifications.length === 0) return null

  return (
    <div className="driver-toast-container" role="region" aria-label="Thông báo phiên sạc">
      {notifications.map(item => (
        <DriverToast key={item.id} notification={item} onDismiss={onDismiss} />
      ))}
    </div>
  )
}

function DriverToast({
  notification,
  onDismiss,
}: {
  notification: DriverNotificationItem
  onDismiss: (id: string) => void
}) {
  const dismiss = useRef(onDismiss)
  useEffect(() => { dismiss.current = onDismiss }, [onDismiss])
  useEffect(() => {
    const remaining = Math.max(0, notification.createdAt + 8000 - Date.now())
    const timer = window.setTimeout(() => dismiss.current(notification.id), remaining)
    return () => window.clearTimeout(timer)
  }, [notification.id, notification.createdAt])

  const iconName =
    notification.type === 'fault'
      ? 'settings'
      : notification.type === 'invoice'
        ? 'report'
        : 'charger'

  return (
    <div
      className={`driver-toast driver-toast-${notification.type}`}
      role={notification.type === 'fault' ? 'alert' : 'status'}
      aria-live={notification.type === 'fault' ? 'assertive' : 'polite'}
    >
      <div className="driver-toast-icon">
        <Icon name={iconName} />
      </div>
      <div className="driver-toast-content">
        <h4 className="driver-toast-title">{notification.title}</h4>
        <p className="driver-toast-message">{notification.message}</p>
        {notification.actionHref && (
          <a
            href={notification.actionHref}
            className="driver-toast-action"
            onClick={() => onDismiss(notification.id)}
          >
            {notification.actionLabel ?? 'Xem chi tiết'}
          </a>
        )}
      </div>
      <button
        type="button"
        className="driver-toast-close"
        aria-label="Đóng thông báo"
        onClick={() => onDismiss(notification.id)}
      >
        <Icon name="close" />
      </button>
    </div>
  )
}
