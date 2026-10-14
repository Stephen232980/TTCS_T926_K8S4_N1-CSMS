import { afterEach, describe, expect, it, vi } from 'vitest'
import { createWalletTopUp, getWalletTopUp, refreshDriverWallet } from './walletTopUpApi'

afterEach(() => vi.unstubAllGlobals())

describe('T-94 - API wallet topups T-93', () => {
  it('POST amount_vnd, cookie; đọc order_id và dùng redirect_url của backend', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 201, json: async () => ({ order_id: 'order-001', redirect_url: 'http://gateway.test/pay/1', status: 'pending' }) }))
    vi.stubGlobal('fetch', fetchMock)
    const created = await createWalletTopUp(200000)
    expect(created).toEqual({ order_id: 'order-001', redirect_url: 'http://gateway.test/pay/1' })
    const [url, options] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/api/v1/driver/wallet/topups')
    expect(options).toMatchObject({ method: 'POST', credentials: 'include' })
    expect(JSON.parse(String(options.body))).toEqual({ amount_vnd: 200000 })
  })

  it('GET trạng thái theo ID có encode và cookie, không lấy query return status', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ status: 'succeeded', order_id: 'order-001' }) }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await getWalletTopUp('order-001')).toMatchObject({ status: 'succeeded' })
    const [url, options] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/api/v1/driver/wallet/topups/order-001')
    expect(options.credentials).toBe('include')
  })

  it('khôi phục order_id từ detail khi lỗi tạo lệnh', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({ detail: { order_id: 'order-ambiguous' } }) })))
    await expect(createWalletTopUp(50000)).rejects.toMatchObject({ kind: 'uncertain', orderId: 'order-ambiguous' })
  })

  it('phân biệt validation, gateway và lỗi mạng chưa rõ kết quả', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ detail: 'Số tiền không hợp lệ' }) })))
    await expect(createWalletTopUp(50000)).rejects.toMatchObject({ kind: 'validation', status: 422 })
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ detail: 'gateway_unavailable' }) })))
    await expect(createWalletTopUp(50000)).rejects.toMatchObject({ kind: 'gateway', status: 503 })
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Network error') }))
    await expect(createWalletTopUp(50000)).rejects.toMatchObject({ kind: 'uncertain' })
  })

  it('bỏ URL nguy hiểm, không chuyển hướng theo javascript:', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 201, json: async () => ({ order_id: 'order-001', redirect_url: 'javascript:alert(1)' }) })))
    await expect(createWalletTopUp(50000)).rejects.toMatchObject({ kind: 'uncertain', orderId: 'order-001' })
  })

  it('chỉ đọc lại dữ liệu ví từ API khi đã được xác nhận', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ balance_vnd: 100000 }) }))
    vi.stubGlobal('fetch', fetchMock)
    await refreshDriverWallet()
    const [url, options] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/api/v1/driver/wallet')
    expect(options.credentials).toBe('include')
    expect(options.method).toBeUndefined()
  })
})
