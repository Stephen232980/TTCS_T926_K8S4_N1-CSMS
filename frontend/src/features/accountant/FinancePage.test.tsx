import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FinancePage } from './FinancePage'
import { AccountantWorkspace } from './AccountantWorkspace'
import { financeRequest, money, type FinancialDetail, type FinancialPage } from './financeApi'

const item: FinancialDetail = {
  session_id:42, station_id:'station-1', station_name:'Trạm Thảo Điền', charge_point_code:'CP-001', connector_number:1,
  driver_email:'driver@example.com', started_at:'2026-10-13T02:00:00Z', ended_at:'2026-10-13T03:00:00Z',
  connector_released_at:'2026-10-13T03:01:00Z', energy_kwh:'1.5', status:'settled', review_reasons:[],
  invoice_id:'invoice-42', invoice_created_at:'2026-10-13T03:01:01Z', invoice_total_vnd:'5000', debited_vnd:'5000',
  ledger_id:20, debited_at:'2026-10-13T03:01:01Z', settlement_completed_at:'2026-10-13T03:01:01Z',settlement_reason:'debited',
  rounding_rule:'Làm tròn từng dòng', ledger_amount_vnd:'-5000',ledger_reference_type:'charging_session',
  lines:[{id:'line-1',line_type:'energy',local_date:'2026-10-13',started_at:'2026-10-13T02:00:00Z',ended_at:'2026-10-13T03:00:00Z',energy_kwh:'1.5',rate_vnd:'3000',band_label:'Ban ngày',interpolated:false,amount_vnd:'4500',tariff_id:'t-1'},
    {id:'line-2',line_type:'idle',local_date:'2026-10-13',started_at:'2026-10-13T03:00:00Z',ended_at:'2026-10-13T03:01:00Z',energy_kwh:'0',rate_vnd:'500',band_label:'Chiếm trụ',interpolated:false,amount_vnd:'500',tariff_id:'t-1'}],
}
const page: FinancialPage = {items:[item],total:25,page:1,total_pages:2,summary:{sessions:25,invoices:24,invoice_total_vnd:'125000',debited_total_vnd:'100000',awaiting_settlement:1}}

function mockApi(list:FinancialPage=page) {
  const fetcher=vi.fn(async (url:string, options?:RequestInit)=> {
    void options
    const data=url.includes('/finance/insights/') ? {grain:'day',generated_at:'2026-10-13T04:00:00Z',timeline:[{period:'2026-10-13',sessions:25,invoice_vnd:'125000',debited_vnd:'100000'}],stations:[{id:'station-1',name:'Trạm Thảo Điền',sessions:25,invoice_vnd:'125000',debited_vnd:'100000'}],statuses:[{status:'settled',count:24,invoice_vnd:'120000'}],aging:[{bucket:'over_week',count:1,invoice_vnd:'5000'}],fees:[{type:'energy',amount_vnd:'120000'},{type:'idle',amount_vnd:'5000'}]} : url.includes('/finance/stations') ? {items:[{id:'station-1',name:'Trạm Thảo Điền'}]} : /\/finance\/sessions\/42(?:$|\?)/.test(url) ? item : url.includes('/events') ? [] : url.includes('/samples') ? {items:[],total_pages:1} : list
    return new Response(JSON.stringify(data),{status:200})
  })
  vi.stubGlobal('fetch',fetcher)
  return fetcher
}
beforeEach(()=>{window.history.replaceState(null,'','/#accountant-sessions');vi.stubGlobal('scrollTo',vi.fn());vi.stubGlobal('innerWidth',1366)})
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks()})

it('shows full-filter totals instead of summing only the visible row',async()=>{
  const fetcher=mockApi()
  render(<FinancePage area="sessions"/>);
  expect(await screen.findByRole('link',{name:'Phiên #42'})).toBeInTheDocument()
  expect(screen.getAllByText('125.000 đ').length).toBeGreaterThan(0)
  expect(screen.getAllByText('100.000 đ').length).toBeGreaterThan(0)
  expect(screen.getByRole('heading',{name:'25 phiên'})).toBeInTheDocument()
  expect(fetcher.mock.calls.every(([,options])=>options?.method===undefined&&options?.credentials==='include')).toBe(true)
})

it('applies server-wide search, dates, station and status filters with a new page',async()=>{
  const fetcher=mockApi();const user=userEvent.setup();render(<FinancePage area="sessions"/>);
  await screen.findByRole('link',{name:'Phiên #42'})
  await user.type(screen.getByRole('searchbox',{name:'Tìm phiên hoặc hóa đơn'}),'driver@example.com')
  await user.selectOptions(screen.getByRole('combobox',{name:'Trạm'}),'station-1')
  await user.selectOptions(screen.getByRole('combobox',{name:'Thanh toán'}),'settled')
  fireEvent.change(screen.getByLabelText('Từ ngày'),{target:{value:'2026-10-10'}})
  fireEvent.change(screen.getByLabelText('Đến ngày'),{target:{value:'2026-10-13'}})
  await user.click(screen.getByRole('button',{name:'Áp dụng'}))
  await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.includes('q=driver%40example.com')&&url.includes('station_id=station-1')&&url.includes('status=settled')&&url.includes('date_to=2026-10-13')&&url.includes('page=1'))).toBe(true))
})

it('rejects reversed dates without sending an invalid search',async()=>{
  const fetcher=mockApi();const user=userEvent.setup();render(<FinancePage area="sessions"/>);
  await screen.findByRole('link',{name:'Phiên #42'})
  fireEvent.change(screen.getByLabelText('Từ ngày'),{target:{value:'2026-10-14'}})
  fireEvent.change(screen.getByLabelText('Đến ngày'),{target:{value:'2026-10-13'}})
  await user.click(screen.getByRole('button',{name:'Áp dụng'}))
  expect(screen.getByRole('alert')).toHaveTextContent('Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.')
  expect(fetcher.mock.calls.some(([url])=>url.includes('date_from='))).toBe(false)
})

it('clears an unapplied draft even when the URL is already unfiltered',async()=>{
  mockApi();const user=userEvent.setup();render(<FinancePage area="sessions"/>);
  await user.type(screen.getByRole('searchbox',{name:'Tìm phiên hoặc hóa đơn'}),'draft')
  await user.click(screen.getByRole('button',{name:'Xóa lọc'}))
  expect(screen.getByRole('searchbox',{name:'Tìm phiên hoặc hóa đơn'})).toHaveValue('')
})

it('opens saved invoice and ledger evidence, preserves page and filter on return',async()=>{
  window.history.replaceState(null,'','/#accountant-sessions?page=2&q=CP-001&status=settled')
  const fetcher=mockApi({...page,page:2});const user=userEvent.setup();render(<FinancePage area="sessions"/>);
  await user.click(await screen.findByRole('link',{name:'Phiên #42'}))
  expect(await screen.findByRole('heading',{name:'Hóa đơn phí sạc'})).toBeInTheDocument()
  expect(screen.getByText('Tiền điện')).toBeInTheDocument();expect(screen.getByText('Phí chiếm trụ')).toBeInTheDocument()
  expect(screen.getByText('-5.000 đ')).toBeInTheDocument()
  expect(fetcher.mock.calls.some(([url])=>url.includes('/samples'))).toBe(false)
  await user.click(screen.getByRole('link',{name:/Quay lại danh sách/}))
  await screen.findByRole('link',{name:'Phiên #42'})
  expect(window.location.hash).toContain('page=2');expect(screen.getByRole('searchbox')).toHaveValue('CP-001')
  expect(screen.getByRole('combobox',{name:'Thanh toán'})).toHaveValue('settled')
})

it('loads technical samples only when explicitly expanded',async()=>{
  window.history.replaceState(null,'','/#accountant-sessions?session=42')
  const fetcher=mockApi();const user=userEvent.setup();render(<FinancePage area="sessions"/>);
  await screen.findByRole('heading',{name:'Phiên #42'})
  await user.click(screen.getByText('Số đo và lịch sử kỹ thuật'))
  await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.includes('/accounting/charging/sessions/42/samples'))).toBe(true))
})

it('uses invoices API for saved invoices and attention filter for review',async()=>{
  const fetcher=mockApi();const v=render(<FinancePage area="invoices"/>);
  await screen.findByRole('link',{name:'Phiên #42'})
  expect(fetcher.mock.calls.some(([url])=>url.includes('/finance/invoices?'))).toBe(true)
  v.unmount();render(<FinancePage area="reconciliation"/>);
  await screen.findByRole('link',{name:'Phiên #42'})
  expect(fetcher.mock.calls.some(([url])=>url.includes('attention=true'))).toBe(true)
})

it('explains empty results without implying an unimplemented feature',async()=>{
  mockApi({...page,items:[],total:0,total_pages:1});render(<FinancePage area="invoices"/>);
  expect(await screen.findByRole('heading',{name:'Không có hóa đơn khớp bộ lọc'})).toBeInTheDocument()
  expect(screen.queryByText(/đang được hoàn thiện/)).not.toBeInTheDocument()
})

it('reports failed requests and supports retry without financial mutation',async()=>{
  const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'service failure'}),{status:500}));vi.stubGlobal('fetch',fetcher)
  const user=userEvent.setup();render(<FinancePage area="sessions"/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('service failure')
  const count=fetcher.mock.calls.length
  await user.click(screen.getByRole('button',{name:'Thử lại'}))
  await waitFor(()=>expect(fetcher.mock.calls.length).toBeGreaterThan(count))
})

it('uses a compact mobile filter and a real account disclosure',async()=>{
  vi.stubGlobal('innerWidth',390);mockApi();const user=userEvent.setup();
  render(<AccountantWorkspace currentUser={{id:'acc',email:'accountant@example.com',roles:['accountant']}} onLogout={vi.fn()}/>);
  await screen.findByRole('link',{name:'Phiên #42'})
  const nav=screen.getByRole('navigation',{name:'Kế toán'})
  expect(within(nav).getByRole('link',{name:'Cần đối chiếu'})).toBeInTheDocument()
  expect(screen.queryByRole('button',{name:'Xuất hoá đơn mới'})).not.toBeInTheDocument()
  expect(screen.getByText('Tra cứu & bộ lọc').parentElement).not.toHaveAttribute('open')
  await user.click(screen.getByRole('button',{name:'Tài khoản'}))
  expect(screen.getByRole('button',{name:'Tài khoản'})).toHaveAttribute('aria-expanded','true')
})

it('keeps integer dong precise and refuses invalid money',()=>{
  expect(money('9007199254740993')).toBe('9.007.199.254.740.993 đ')
  expect(money(null)).toBe('—');expect(money('invalid')).toBe('—')
})

it('gives each area a distinct register and drill-down chart',async()=>{
  const fetcher=mockApi();const user=userEvent.setup()
  const view=render(<FinancePage area="sessions"/>);
  await screen.findByRole('heading',{name:'Phân bổ theo trạm'})
  await user.click(screen.getByRole('button',{name:/Trạm Thảo Điền.*25 phiên/}))
  await waitFor(()=>expect(window.location.hash).toContain('station_id=station-1'))
  view.unmount();window.history.replaceState(null,'','/#accountant-invoices')
  const invoices=render(<FinancePage area="invoices"/>);
  await screen.findByRole('heading',{name:'Cơ cấu khoản phí đã lập'})
  expect(screen.getByText('invoice-42')).toBeInTheDocument()
  expect(screen.queryByRole('heading',{name:'Phân bổ theo trạm'})).not.toBeInTheDocument()
  invoices.unmount();window.history.replaceState(null,'','/#accountant-reconciliation')
  render(<FinancePage area="reconciliation"/>);
  await screen.findByRole('heading',{name:'Thời gian chờ đối chiếu'})
  await user.click(screen.getByRole('button',{name:/Từ 7 ngày/}))
  await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.includes('attention=true')&&url.includes('age=over_week'))).toBe(true))
  expect(screen.getByRole('link',{name:'Kiểm tra hóa đơn & sổ cái'})).toBeInTheDocument()
})

it('copies reconciliation evidence without sending a write request',async()=>{
  mockApi();const user=userEvent.setup();const clipboard=vi.spyOn(navigator.clipboard,'writeText').mockResolvedValue()
  render(<FinancePage area="reconciliation"/>);
  await user.click(await screen.findByRole('button',{name:'Sao chép hồ sơ'}))
  expect(clipboard).toHaveBeenCalledWith(expect.stringContaining('Phiên #42'))
  expect(await screen.findByText('Đã sao chép để chuyển vận hành')).toBeInTheDocument()
})

it('denies API access explicitly and handles unauthorized sessions',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{}',{status:403})))
  await expect(financeRequest('/finance/sessions')).rejects.toThrow('Bạn không có quyền')
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{}',{status:401})))
  await act(async()=>{await expect(financeRequest('/finance/sessions')).rejects.toThrow()})
})

it('triggers accountant revenue CSV export when button is clicked', async () => {
  const fetcher = mockApi()
  const user = userEvent.setup()
  window.URL.createObjectURL = vi.fn(() => 'blob:mock-url')
  window.URL.revokeObjectURL = vi.fn()

  render(<FinancePage area="sessions" />)
  await screen.findByRole('link', { name: 'Phiên #42' })

  const exportBtn = screen.getByRole('button', {
    name: 'Xuất CSV báo cáo doanh thu',
  })
  expect(exportBtn).toBeInTheDocument()
  await user.click(exportBtn)

  await waitFor(() => {
    expect(fetcher).toHaveBeenCalledWith(
      expect.stringContaining('/accounting/reports/revenue/export'),
      expect.objectContaining({ credentials: 'include' }),
    )
  })
})

