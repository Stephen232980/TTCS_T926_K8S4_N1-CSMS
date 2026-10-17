export type DriverNotificationType = 'stop' | 'idle' | 'fault' | 'invoice'

export interface DriverNotificationItem {
  id: string
  sessionId: number
  type: DriverNotificationType
  title: string
  message: string
  actionHref?: string
  actionLabel?: string
  createdAt: number
}

export function emitBrowserNotification(title: string, options?: NotificationOptions) {
  if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
    try {
      return new Notification(title, options)
    } catch {
      return null
    }
  }
  return null
}
