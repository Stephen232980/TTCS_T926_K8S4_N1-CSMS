// PAYMENT_RETURN_URL is configured by the backend/gateway. Support path and
// hash-based SPA returns; order_code is an identifier, NOT a payment status.
export function readTopUpReturn(location: Pick<Location, 'pathname' | 'search' | 'hash'>): {
  isReturn: boolean
  orderId: string
} {
  const query = new URLSearchParams(location.search)
  const hash = location.hash.replace(/^#/, '')
  const hashRoute = hash.split('?')[0]
  const hashQuery = hash.includes('?') ? new URLSearchParams(hash.slice(hash.indexOf('?') + 1)) : null
  const route = /(?:wallet\/?topups?\/?return|wallet\/return|payment\/return|driver-wallet-return)/i
  const order = query.get('order_code') ?? hashQuery?.get('order_code') ?? ''
  const isReturn = query.has('order_code') || Boolean(hashQuery?.has('order_code')) ||
    route.test(location.pathname) || route.test(hashRoute)
  return { isReturn, orderId: order.trim() }
}
