import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { DriverWalletApi, DriverWallet, WalletLedgerList } from './api/driverWalletApi'
import { DriverWalletPage } from './DriverWalletPage'

describe('DriverWalletPage (S-40 / T-100)', () => {
  const mockWallet: DriverWallet = {
    id: 'wallet-1',
    driver_id: 'driver-1',
    balance: '250000.00',
    currency: 'VND',
    status: 'active',
    is_negative: false,
    debt_amount: '0.00',
  }

  const mockLedgerPage1: WalletLedgerList = {
    items: [
      {
        id: 2,
        wallet_id: 'wallet-1',
        amount: '-50000.00',
        balance_after: '250000.00',
        entry_type: 'charge',
        reference_type: 'session',
        reference_id: 'CS-901',
        description: 'Thanh toán phiên sạc tại Landmark 81',
        created_at: '2026-10-08T00:10:00Z',
      },
      {
        id: 1,
        wallet_id: 'wallet-1',
        amount: '300000.00',
        balance_after: '300000.00',
        entry_type: 'topup',
        reference_type: 'payment_gateway',
        reference_id: 'PG-001',
        description: 'Nạp tiền qua VNPay',
        created_at: '2026-10-07T22:00:00Z',
      },
    ],
    next_cursor: 1,
    has_more: true,
  }

  const mockLedgerPage2: WalletLedgerList = {
    items: [
      {
        id: 0,
        wallet_id: 'wallet-1',
        amount: '10000.00',
        balance_after: '10000.00',
        entry_type: 'topup',
        reference_type: 'manual_receipt',
        reference_id: 'MR-000',
        description: 'Nạp thử nghiệm tài khoản mới',
        created_at: '2026-10-07T20:00:00Z',
      },
    ],
    next_cursor: null,
    has_more: false,
  }

  it('renders positive balance and transaction feed', async () => {
    const api: DriverWalletApi = {
      getWallet: vi.fn().mockResolvedValue(mockWallet),
      getTransactions: vi.fn().mockResolvedValue(mockLedgerPage1),
    }

    render(<DriverWalletPage walletApi={api} />)

    expect(await screen.findByText('250.000 ₫')).toBeInTheDocument()
    expect(screen.getByText('Thanh toán phiên sạc tại Landmark 81')).toBeInTheDocument()
    expect(screen.getByText('-50.000 ₫')).toBeInTheDocument()
    expect(screen.getByText('Nạp tiền qua VNPay')).toBeInTheDocument()
    expect(screen.getByText('+300.000 ₫')).toBeInTheDocument()
    expect(screen.getByText('Mã dòng #2')).toBeInTheDocument()
  })

  it('displays debt warning when balance is negative (S-40 debt warning)', async () => {
    const debtWallet: DriverWallet = {
      ...mockWallet,
      balance: '-35000.00',
      is_negative: true,
      debt_amount: '35000.00',
    }

    const api: DriverWalletApi = {
      getWallet: vi.fn().mockResolvedValue(debtWallet),
      getTransactions: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false }),
    }

    render(<DriverWalletPage walletApi={api} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Cảnh báo nợ ví')
    expect(screen.getByText(/Số dư đang âm 35.000 ₫/)).toBeInTheDocument()
  })

  it('supports cursor pagination when loading more transactions', async () => {
    const user = userEvent.setup()
    const getTransactionsMock = vi
      .fn()
      .mockResolvedValueOnce(mockLedgerPage1)
      .mockResolvedValueOnce(mockLedgerPage2)

    const api: DriverWalletApi = {
      getWallet: vi.fn().mockResolvedValue(mockWallet),
      getTransactions: getTransactionsMock,
    }

    render(<DriverWalletPage walletApi={api} />)

    const loadMoreBtn = await screen.findByRole('button', {
      name: 'Tải thêm giao dịch cũ hơn',
    })
    expect(loadMoreBtn).toBeInTheDocument()

    await user.click(loadMoreBtn)

    await waitFor(() => {
      expect(getTransactionsMock).toHaveBeenCalledWith({
        limit: 10,
        cursor: 1,
      }, expect.any(AbortSignal))
    })

    expect(await screen.findByText('Nạp thử nghiệm tài khoản mới')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tải thêm giao dịch cũ hơn' })).not.toBeInTheDocument()
  })

  it('does not invent wallet data after an initial failure and supports retry', async () => {
    const api: DriverWalletApi = {
      getWallet: vi.fn().mockRejectedValueOnce(new Error('Mất kết nối')).mockResolvedValue(mockWallet),
      getTransactions: vi.fn().mockResolvedValue(mockLedgerPage1),
    }
    render(<DriverWalletPage walletApi={api} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Mất kết nối')
    for (const text of ['0 ₫', 'Tạm khóa', 'Hoạt động']) expect(screen.queryByText(text)).not.toBeInTheDocument()
    expect(screen.queryByText(/Chưa có giao dịch/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Số dư hiện tại thấp hơn/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('250.000 ₫')).toBeInTheDocument()
  })

  it('locks refresh during pagination then replaces the list on refresh', async () => {
    let resolvePage!: (page: WalletLedgerList) => void
    const pending = new Promise<WalletLedgerList>(resolve => { resolvePage = resolve })
    const getTransactions = vi.fn().mockResolvedValueOnce(mockLedgerPage1).mockReturnValueOnce(pending).mockResolvedValueOnce(mockLedgerPage1)
    render(<DriverWalletPage walletApi={{ getWallet: vi.fn().mockResolvedValue(mockWallet), getTransactions }} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tải thêm giao dịch cũ hơn' }))
    const refresh = screen.getByRole('button', { name: 'Làm mới' })
    expect(refresh).toBeDisabled()
    await userEvent.click(refresh)
    expect(getTransactions).toHaveBeenCalledTimes(2)
    await act(async () => resolvePage(mockLedgerPage2))
    expect(screen.getByText('Nạp thử nghiệm tài khoản mới')).toBeInTheDocument()
    await userEvent.click(refresh)
    await waitFor(() => expect(screen.queryByText('Nạp thử nghiệm tài khoản mới')).not.toBeInTheDocument())
    expect(screen.getAllByText('Mã dòng #2')).toHaveLength(1)
  })

  it('opens the referenced session and explains unavailable topup details', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 901, station_name: 'Trạm A', energy_kwh: 12 })))
    try {
      const page = { ...mockLedgerPage1, items: mockLedgerPage1.items.map(tx => tx.id === 2 ? { ...tx, reference_type: 'charging_session', reference_id: '901' } : tx) }
      render(<DriverWalletPage walletApi={{ getWallet: vi.fn().mockResolvedValue(mockWallet), getTransactions: vi.fn().mockResolvedValue(page) }} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Xem phiên sạc #901' }))
      expect(fetchMock).toHaveBeenCalledWith('/api/v1/driver/charging/sessions/901', { credentials: 'include', signal: expect.any(AbortSignal) })
      expect(await screen.findByRole('region', { name: 'Chi tiết phiên sạc' })).toHaveTextContent('Trạm A · 12 kWh')
      expect(screen.getByText(/Chi tiết lần nạp chưa khả dụng/)).toBeInTheDocument()
    } finally { fetchMock.mockRestore() }
  })

  it('opens and closes the topup dialog modal', async () => {
    const user = userEvent.setup()
    const api: DriverWalletApi = {
      getWallet: vi.fn().mockResolvedValue(mockWallet),
      getTransactions: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false }),
    }

    render(<DriverWalletPage walletApi={api} />)

    const topupBtn = await screen.findByRole('button', { name: 'Nạp tiền vào ví' })
    await user.click(topupBtn)

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Nạp tiền vào ví tài xế')).toBeInTheDocument()

    const closeBtn = screen.getByRole('button', { name: 'Đã hiểu' })
    await user.click(closeBtn)

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })
})
