
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { WalletTopUpReturn } from './WalletTopUpReturn'

describe('T-94 - Trạng thái nạp tiền', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('tự kiểm tra và cập nhật sau webhook trễ 10 giây', async () => {
    const startedAt = Date.now()

    const getStatus = vi.fn(async () => ({
      status: Date.now() - startedAt >= 10000
        ? 'success' as const
        : 'pending' as const,
    }))

    render(
      <WalletTopUpReturn
        transactionId="tx-001"
        getStatus={getStatus}
      />,
    )

    expect(screen.getByText(/Đang chờ hệ thống/)).toBeTruthy()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(12000)
    })

    expect(screen.getByText(/Nạp tiền thành công/)).toBeTruthy()
    expect(getStatus).toHaveBeenCalledTimes(5)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })

    expect(getStatus).toHaveBeenCalledTimes(5)
  })

  it.each([
    {
      status: 'failed' as const,
      message: /Nạp tiền thất bại/,
      reason: 'Thanh toán bị từ chối',
    },
    {
      status: 'cancelled' as const,
      message: /Giao dịch đã bị huỷ/,
      reason: 'Người dùng huỷ thanh toán',
    },
  ])('hiển thị đúng trạng thái $status', async ({
    status,
    message,
    reason,
  }) => {
    const getStatus = vi.fn().mockResolvedValue({
      status,
      reason,
    })

    render(
      <WalletTopUpReturn
        transactionId="tx-002"
        getStatus={getStatus}
      />,
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.getByText(message)).toBeTruthy()
    expect(screen.getByText(new RegExp(reason))).toBeTruthy()
  })

  it('dừng polling sau 2 phút nếu vẫn đang chờ', async () => {
    const getStatus = vi.fn().mockResolvedValue({
      status: 'pending',
    })

    render(
      <WalletTopUpReturn
        transactionId="tx-003"
        getStatus={getStatus}
      />,
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120000)
    })

    expect(
      screen.getByText(/Đã hết thời gian chờ tự động/),
    ).toBeTruthy()

    const calls = getStatus.mock.calls.length

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000)
    })

    expect(getStatus).toHaveBeenCalledTimes(calls)
  })
})
