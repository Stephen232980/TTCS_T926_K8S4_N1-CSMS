export const SESSION_UNAUTHORIZED_EVENT = 'csms:session-unauthorized'

export function notifySessionUnauthorized(): void {
  window.dispatchEvent(new Event(SESSION_UNAUTHORIZED_EVENT))
}
