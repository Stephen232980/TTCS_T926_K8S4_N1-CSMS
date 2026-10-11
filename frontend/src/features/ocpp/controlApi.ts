import { notifySessionUnauthorized } from '../auth/sessionEvents'

export const controlStatuses: Record<string, string> = {
  Pending: 'Đang chờ phản hồi từ trụ…', Accepted: 'Trụ đã chấp nhận lệnh.',
  Rejected: 'Trụ từ chối lệnh. Phiên sạc được giữ nguyên.', Offline: 'Trụ đang ngoại tuyến. Không gửi lệnh.',
  Timeout: 'Trụ không phản hồi trong 30 giây. Yêu cầu đã hết hạn.',
  Disconnected: 'Trụ mất kết nối trong lúc chờ phản hồi.', ProtocolError: 'Phản hồi từ trụ không hợp lệ.',
}
export async function controlRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
  const response = await fetch(`${base}/api/v1/ocpp${path}`, { credentials: 'include', ...options })
  if (response.status === 401) notifySessionUnauthorized()
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown }
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Không thực hiện được yêu cầu. Hãy thử lại.')
  }
  return await response.json() as T
}
