import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DriverInvoicePage } from './DriverInvoicePage'
import { invoiceMoney, type DriverInvoice, type DriverInvoiceApi } from './driverInvoiceApi'

const invoice: DriverInvoice = {
  session_id: 42, station_name: 'Trạm thử', status: 'ready', ended_at: '2026-10-10T03:00:00Z',
  invoice_id: 'invoice-snapshot', created_at: '2026-10-10T03:00:01Z', total_vnd: '3500',
  rounding_rule: 'Làm tròn từng dòng rồi cộng tổng',
  lines: [
    { id:'energy', line_type:'energy', local_date:'2026-10-10', started_at:'2026-10-10T02:00:00Z', ended_at:'2026-10-10T03:00:00Z', energy_kwh:'1.000125', rate_vnd:'3000', amount_vnd:'3000', band_label:'Ban ngày', interpolated:true, tariff_id:'version-old' },
    { id:'idle', line_type:'idle', local_date:'2026-10-10', started_at:'2026-10-10T02:55:00Z', ended_at:'2026-10-10T03:00:00Z', energy_kwh:'0', rate_vnd:'100', amount_vnd:'500', band_label:'Chiếm trụ', interpolated:false, tariff_id:'version-old' },
  ],
}
const apiFor = (data: DriverInvoice): DriverInvoiceApi => ({get:vi.fn().mockResolvedValue(data),list:vi.fn()})
describe('T-82 invoice snapshots', () => {
  it('shows energy, idle, saved rates, rounding and saved total', async () => {
    render(<DriverInvoicePage sessionId={42} api={apiFor(invoice)} onOpen={vi.fn()} onBack={vi.fn()} />)
    expect(await screen.findByText(/Tổng cộng/)).toHaveTextContent('3.500 đ')
    expect(screen.getByText('1,000125 kWh')).toBeTruthy()
    expect(screen.getByText('3.000 đ/kWh')).toBeTruthy()
    expect(screen.getByText('100 đ/phút')).toBeTruthy()
    expect(screen.getByText(/Quy tắc làm tròn/)).toHaveTextContent(invoice.rounding_rule!)
    expect(screen.getByText(/Số đo tại ranh giới/)).toBeTruthy()
  })
  it.each(['needs_review', 'pending', 'in_progress'] as const)('hides amounts for %s even if a response contains money', async status => {
    render(<DriverInvoicePage sessionId={42} api={apiFor({...invoice,status})} onOpen={vi.fn()} onBack={vi.fn()} />)
    await screen.findByText(/chưa có số tiền được xác nhận/)
    expect(screen.queryByText(/Tổng cộng/)).toBeNull()
    expect(screen.queryByText(/3.500/)).toBeNull()
  })
  it('ignores a late response from a previous session', async () => {
    let finish!: (value: DriverInvoice) => void
    const api: DriverInvoiceApi = {list:vi.fn(),get:vi.fn(id => id === 42
      ? new Promise<DriverInvoice>(resolve => { finish=resolve })
      : Promise.resolve({...invoice,session_id:43,total_vnd:'0'}))}
    const view=render(<DriverInvoicePage sessionId={42} api={api} onOpen={vi.fn()} onBack={vi.fn()} />)
    view.rerender(<DriverInvoicePage sessionId={43} api={api} onOpen={vi.fn()} onBack={vi.fn()} />)
    await screen.findByText(/Tổng cộng/)
    finish(invoice)
    await waitFor(() => expect(screen.getByText(/Tổng cộng/)).toHaveTextContent('0 đ'))
  })
  it('opens selected session and paginates invoice candidates', async () => {
    const api:DriverInvoiceApi={get:vi.fn(),list:vi.fn().mockResolvedValue({items:[invoice],next_cursor:42})}
    const open=vi.fn(), user=userEvent.setup()
    render(<DriverInvoicePage api={api} onOpen={open} onBack={vi.fn()} />)
    await user.click(await screen.findByRole('button',{name:/Phiên #42/}))
    expect(open).toHaveBeenCalledWith(42)
    await user.click(screen.getByRole('button',{name:'Xem các phiên cũ hơn'}))
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(42,expect.any(AbortSignal)))
  })
  it('allows retry after a read error', async () => {
    const api=apiFor(invoice)
    vi.mocked(api.get).mockRejectedValueOnce(new Error('Bạn không có quyền xem hóa đơn này.'))
    render(<DriverInvoicePage sessionId={42} api={api} onOpen={vi.fn()} onBack={vi.fn()} />)
    await screen.findByRole('alert')
    await userEvent.click(screen.getByRole('button',{name:'Kiểm tra lại'}))
    await screen.findByText(/Tổng cộng/)
  })
  it('formats BIGINT money without rounding through Number', () => {
    expect(invoiceMoney('9007199254740993')).toBe('9.007.199.254.740.993 đ')
  })
})
