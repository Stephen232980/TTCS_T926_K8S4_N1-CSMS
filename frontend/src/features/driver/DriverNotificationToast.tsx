import { useEffect } from 'react'
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
        <DriverToast key={item.id} notification={item} onDismiss={() => onDismiss(item.id)} />
      ))}
    </div>
  )
}

function DriverToast({
  notification,
  onDismiss,
}: {
  notification: DriverNotificationItem
  onDismiss: () => void
}) {
  useEffect(() => {
    const timer = window.setTimeout(onDismiss, 8000)
    return () => window.clearTimeout(timer)
  }, [onDismiss])

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
            onClick={onDismiss}
          >
            {notification.actionLabel ?? 'Xem chi tiết'}
          </a>
        )}
      </div>
      <button
        type="button"
        className="driver-toast-close"
        aria-label="Đóng thông báo"
        onClick={onDismiss}
      >
        <Icon name="close" />
      </button>
    </div>
  )
}
