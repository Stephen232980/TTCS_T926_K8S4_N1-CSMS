import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AdminWalletAudit } from './AdminWalletAudit'
const admin = { id: 'a', email: 'admin@example.com', roles: ['admin'] }
const row = { id: 'log', actor_id: 'actor', driver_id: 'driver', wallet_id: 'wallet', action: 'wallet.manual_topup', occurred_at: '2026-10-17T00:00:00Z', amount_vnd: 100000, before_balance_vnd: 0, after_balance_vnd: 100000, reason: 'Thu tiền mặt', legacy: false, ledger_id: 12, reference_type: 'manual_topup', reference_id: 'PT-001', reservation_id: null, before_decision: null, decision: null }
afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('loads compact rows and opens receipt evidence only on demand', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ items: [row], total: 1, total_pages: 1 })))
  render(<AdminWalletAudit currentUser={admin} />)
  const receipt = await screen.findByText('manual_topup: PT-001')
  expect(receipt.closest('details')).not.toHaveAttribute('open')
  fireEvent.click(screen.getByText(/Nạp tay ·/))
  expect(receipt.closest('details')).toHaveAttribute('open')
  expect(screen.getByText('Thu tiền mặt')).toBeInTheDocument()
})
it('sends driver and wallet filters with 50 rows and resets pagination', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ items: [], total: 101, total_pages: 3 })))
  render(<AdminWalletAudit currentUser={admin} />)
  await screen.findByText('Không có nhật ký phù hợp.')
  fireEvent.click(screen.getByRole('button', { name: 'Sau' }))
  await waitFor(() => expect(String(fetcher.mock.calls.at(-1)?.[0])).toContain('page=2'))
  fireEvent.change(screen.getByLabelText('Mã tài xế'), { target: { value: 'driver-id' } })
  fireEvent.change(screen.getByLabelText('Mã ví'), { target: { value: 'wallet-id' } })
  fireEvent.click(screen.getByRole('button', { name: 'Lọc' }))
  await waitFor(() => expect(String(fetcher.mock.calls.at(-1)?.[0])).toContain('driver_id=driver-id&wallet_id=wallet-id&page=1&page_size=50'))
})
it('shows historical missing data without inventing a reason', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ items: [{ ...row, reason: null, legacy: true }], total: 1, total_pages: 1 })))
  render(<AdminWalletAudit currentUser={admin} />)
  expect(await screen.findByText('Chưa ghi nhận')).toBeInTheDocument()
  expect(screen.getByText(/Bản ghi cũ/)).toBeInTheDocument()
})
it.each(['driver', 'station_owner', 'operator', 'accountant'])('hides wallet audit for %s without loading it', role => {
  const fetcher = vi.spyOn(globalThis, 'fetch')
  render(<AdminWalletAudit currentUser={{ ...admin, roles: [role] }} />)
  expect(screen.getByRole('alert')).toHaveTextContent('không có quyền')
  expect(fetcher).not.toHaveBeenCalled()
})
