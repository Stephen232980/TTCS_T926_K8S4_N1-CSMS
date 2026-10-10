import { describe, expect, it } from 'vitest'
import { readTopUpReturn } from './walletTopUpReturnUrl'

describe('T-94 - URL gateway quay về', () => {
  it('đọc order_code từ search, bỏ qua status trên URL', () => {
    expect(readTopUpReturn({ pathname: '/', search: '?order_code=abc-123&status=succeeded', hash: '' })).toEqual({ isReturn: true, orderId: 'abc-123' })
  })
  it('đọc order_code từ hash route của SPA', () => {
    expect(readTopUpReturn({ pathname: '/', search: '', hash: '#driver-wallet-return?order_code=xyz' })).toEqual({ isReturn: true, orderId: 'xyz' })
  })
  it('nhận URL thiếu order_code trên return path', () => {
    expect(readTopUpReturn({ pathname: '/wallet/topup/return', search: '', hash: '' })).toEqual({ isReturn: true, orderId: '' })
  })
  it('không nhầm màn ví bình thường thành gateway return', () => {
    expect(readTopUpReturn({ pathname: '/', search: '', hash: '#driver-wallet' })).toEqual({ isReturn: false, orderId: '' })
  })
})
