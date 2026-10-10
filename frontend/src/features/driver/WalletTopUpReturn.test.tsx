import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { WalletTopUpReturn } from './WalletTopUpReturn'
import { WalletTopUpApiError, type TopUpStatus } from './walletTopUpApi'

describe('T-94 - Trạng thái nạp tiền', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { cleanup(); vi.useRealTimers() })

  it('polling mỗi ba giây, cập nhật sau webhook trễ 10 giây và dừng', async () => {
    const startedAt = Date.now()
    const getStatus = vi.fn(async () => ({
      status: (Date.now() - startedAt >= 10000 ? 'succeeded' : 'pending') as TopUpStatus,
    }))
    const onSucceeded = vi.fn(async () => {})
    render(<WalletTopUpReturn transactionId="order-001" getStatus={getStatus} onSucceeded={onSucceeded} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(12000) })
    expect(screen.getByText(/Backend đã xác nhận nạp tiền thành công/)).toBeTruthy()
    expect(getStatus).toHaveBeenCalledTimes(5)
    expect(onSucceeded).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(getStatus).toHaveBeenCalledTimes(5)
  })

  it.each([
    { status: 'failed' as const, match: /Nạp tiền thất bại/, reason: 'Thanh toán bị từ chối' },
    { status: 'cancelled' as const, match: /Giao dịch đã bị huỷ/, reason: 'Người dùng huỷ' },
    { status: 'needs_review' as const, match: /cần kiểm tra thủ công/, reason: 'Chờ đối soát' },
  ])('hiển thị $status theo T-93 và lý do', async ({ status, match, reason }) => {
    const getStatus = vi.fn().mockResolvedValue({ status, reason })
    render(<WalletTopUpReturn transactionId="order-002" getStatus={getStatus} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(screen.getByText(match)).toBeTruthy()
    expect(screen.getByText(new RegExp(reason))).toBeTruthy()
  })

  it('timeout đúng 2 phút nếu pending', async () => {
    const getStatus = vi.fn().mockResolvedValue({ status: 'pending' })
    render(<WalletTopUpReturn transactionId="order-003" getStatus={getStatus} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(120000) })
    expect(screen.getByText(/Đã hết thời gian chờ tự động/)).toBeTruthy()
    const calls = getStatus.mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
    expect(getStatus).toHaveBeenCalledTimes(calls)
  })

  it('request treo vẫn timeout; response muộn bị bỏ qua', async () => {
    let complete!: (value: { status: TopUpStatus }) => void
    const getStatus = vi.fn(() => new Promise<{ status: TopUpStatus }>(resolve => { complete = resolve }))
    const onSucceeded = vi.fn()
    render(<WalletTopUpReturn transactionId="order-004" getStatus={getStatus} onSucceeded={onSucceeded} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(123000) })
    expect(screen.getByText(/Đã hết thời gian chờ tự động/)).toBeTruthy()
    expect(getStatus).toHaveBeenCalledTimes(1)
    await act(async () => { complete({ status: 'succeeded' }); await Promise.resolve() })
    expect(screen.queryByText(/Backend đã xác nhận nạp tiền thành công/)).toBeNull()
    expect(onSucceeded).not.toHaveBeenCalled()
  })

  it('đổi mã lệnh thì reset dữ liệu cũ và bỏ qua response muộn', async () => {
    let completeOld!: (value: { status: TopUpStatus }) => void
    const getStatus = vi.fn((id: string) => id === 'old'
      ? new Promise<{ status: TopUpStatus }>(resolve => { completeOld = resolve })
      : Promise.resolve({ status: 'failed' as const, reason: 'Từ chối' }))
    const { rerender } = render(<WalletTopUpReturn transactionId="old" getStatus={getStatus} />)
    rerender(<WalletTopUpReturn transactionId="new" getStatus={getStatus} />)
    await act(async () => { completeOld({ status: 'succeeded' }); await vi.advanceTimersByTimeAsync(0) })
    expect(screen.getByText(/Nạp tiền thất bại/)).toBeTruthy()
    expect(screen.queryByText(/Backend đã xác nhận nạp tiền thành công/)).toBeNull()
  })

  it('unmount dọn timer và không xử lý response tới muộn', async () => {
    let finish!: (value: { status: TopUpStatus }) => void
    const getStatus = vi.fn(() => new Promise<{ status: TopUpStatus }>(resolve => { finish = resolve }))
    const onSucceeded = vi.fn()
    const view = render(<WalletTopUpReturn transactionId="order-005" getStatus={getStatus} onSucceeded={onSucceeded} />)
    view.unmount()
    await act(async () => { finish({ status: 'succeeded' }); await vi.advanceTimersByTimeAsync(150000) })
    expect(getStatus).toHaveBeenCalledTimes(1)
    expect(onSucceeded).not.toHaveBeenCalled()
  })

  it('thiếu order_code và mã không tồn tại đều có thông báo', async () => {
    const getStatus = vi.fn().mockRejectedValue(new WalletTopUpApiError('not_found', 'Không tìm thấy lệnh.', 404))
    const { rerender } = render(<WalletTopUpReturn transactionId="" getStatus={getStatus} />)
    expect(screen.getByText(/URL quay về thiếu mã đơn/)).toBeTruthy()
    expect(getStatus).not.toHaveBeenCalled()
    rerender(<WalletTopUpReturn transactionId="absent" getStatus={getStatus} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(screen.getByText(/Không tìm thấy lệnh/)).toBeTruthy()
  })
})
