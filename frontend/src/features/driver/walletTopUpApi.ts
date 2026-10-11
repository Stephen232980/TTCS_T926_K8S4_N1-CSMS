import { notifySessionUnauthorized } from '../auth/sessionEvents'

export type TopUpStatus =
  | 'pending'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'needs_review'

export interface TopUpResult {
  status: TopUpStatus
  reason?: string | null
  order_id?: string
}

export interface TopUpCreated {
  order_id: string
  redirect_url: string
}

export type TopUpErrorKind =
  | 'validation'
  | 'auth'
  | 'gateway'
  | 'not_found'
  | 'uncertain'
  | 'other'

export class WalletTopUpApiError extends Error {
  readonly kind: TopUpErrorKind
  readonly status?: number
  readonly orderId?: string

  constructor(
    kind: TopUpErrorKind,
    message: string,
    status?: number,
    orderId?: string,
  ) {
    super(message)
    this.name = 'WalletTopUpApiError'
    this.kind = kind
    this.status = status
    this.orderId = orderId
  }
}

const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
const root = `${base}/api/v1/driver/wallet`

function obj(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

async function body(response: Response): Promise<unknown> {
  try { return await response.json() as unknown } catch { return null }
}

function apiError(status: number, data: unknown): WalletTopUpApiError {
  const detail = obj(data)?.detail
  const fields = obj(detail)
  const orderId = text(fields?.order_id) ?? text(obj(data)?.order_id)
  const message = typeof detail === 'string'
    ? detail
    : text(fields?.message) ?? text(fields?.reason)
  if (status === 401) {
    notifySessionUnauthorized()
    return new WalletTopUpApiError('auth', 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.', status, orderId)
  }
  if (status === 403) return new WalletTopUpApiError('auth', 'Bạn không có quyền truy cập giao dịch này.', status, orderId)
  if (status === 404) return new WalletTopUpApiError('not_found', 'Không tìm thấy lệnh nạp tiền này.', status, orderId)
  if (status === 400 || status === 422) return new WalletTopUpApiError('validation', message ?? 'Số tiền nạp không hợp lệ.', status, orderId)
  if (status === 502 || status === 503 || status === 504) {
    return new WalletTopUpApiError('gateway', 'Cổng thanh toán hiện không khả dụng. Chưa thể xác định lệnh đã được tạo hay chưa.', status, orderId)
  }
  if (status >= 500 || status === 408 || status === 409) {
    return new WalletTopUpApiError('uncertain', 'Chưa xác định được kết quả tạo lệnh. Không gửi lệnh nạp mới trước khi kiểm tra.', status, orderId)
  }
  return new WalletTopUpApiError('other', message ?? 'Không thể xử lý yêu cầu nạp tiền.', status, orderId)
}

export async function createWalletTopUp(amount: number): Promise<TopUpCreated> {
  if (!Number.isSafeInteger(amount) || amount < 10000 || amount > 5000000) {
    throw new WalletTopUpApiError('validation', 'Số tiền phải từ 10.000 đến 5.000.000 VNĐ.')
  }
  let response: Response
  try {
    response = await fetch(`${root}/topups`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount_vnd: amount }),
    })
  } catch {
    throw new WalletTopUpApiError('uncertain', 'Mất kết nối khi tạo lệnh. Có thể lệnh đã được tạo; không tự gửi lại.')
  }
  const data = await body(response)
  if (!response.ok) throw apiError(response.status, data)
  const responseData = obj(data)
  const orderId = text(responseData?.order_id)
  const redirectUrl = text(responseData?.redirect_url)
  if (responseData?.status !== undefined && responseData.status !== 'pending') {
    throw new WalletTopUpApiError('uncertain', 'Backend chưa xác nhận lệnh ở trạng thái chờ thanh toán.', response.status, orderId)
  }
  if (!orderId || !redirectUrl) {
    throw new WalletTopUpApiError('uncertain', 'Backend đã nhận yêu cầu nhưng thiếu mã lệnh hoặc URL thanh toán.', response.status, orderId)
  }
  // Only navigate to http(s) URLs returned by the backend. Never compose gateway links.
  try {
    const url = new URL(redirectUrl, window.location.href)
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('bad protocol')
  } catch {
    throw new WalletTopUpApiError('uncertain', 'URL thanh toán do backend trả về không hợp lệ.', response.status, orderId)
  }
  return { order_id: orderId, redirect_url: redirectUrl }
}

export async function getWalletTopUp(orderId: string, signal?: AbortSignal): Promise<TopUpResult> {
  if (!orderId.trim()) throw new WalletTopUpApiError('validation', 'Thiếu mã lệnh nạp tiền.')
  let response: Response
  try {
    response = await fetch(`${root}/topups/${encodeURIComponent(orderId)}`, { credentials: 'include', signal })
  } catch (cause) {
    if (signal?.aborted) throw cause
    throw new WalletTopUpApiError('uncertain', 'Không thể kết nối để đọc trạng thái lệnh nạp tiền.')
  }
  const data = await body(response)
  if (!response.ok) throw apiError(response.status, data)
  const result = obj(data)
  const status = result?.status
  if (!['pending', 'succeeded', 'failed', 'cancelled', 'needs_review'].includes(String(status))) {
    throw new WalletTopUpApiError('other', 'Backend trả về trạng thái lệnh không xác định.')
  }
  return {
    status: status as TopUpStatus,
    order_id: text(result?.order_id),
    reason: text(result?.reason) ?? text(result?.failure_reason),
  }
}

// A successful payment is confirmed by GET topup status, not by callback query params.
// Refreshing the wallet invokes the backend; no balance is calculated locally.
export async function refreshDriverWallet(): Promise<void> {
  let response: Response
  try { response = await fetch(root, { credentials: 'include' }) }
  catch { throw new WalletTopUpApiError('uncertain', 'Không tải lại được dữ liệu ví.') }
  if (!response.ok) throw apiError(response.status, await body(response))
  await body(response)
}
