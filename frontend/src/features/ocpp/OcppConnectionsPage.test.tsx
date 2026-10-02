import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OcppConnectionsPage } from './OcppConnectionsPage'
class FakeEventSource {
  static instances: FakeEventSource[] = []
  onmessage: ((event: {data: string}) => void) | null = null
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()
  addEventListener = vi.fn()
  constructor() { FakeEventSource.instances.push(this) }
}
afterEach(() => { vi.unstubAllGlobals(); FakeEventSource.instances = [] })
const connector = { id:'connector',number:1,status:'Available',raw_ocpp_status:'Available',status_updated_at:'2026-10-02T08:00:00Z',last_error_code:null,last_vendor_error_code:null,last_error_at:null }
const charger = { id:'one',code:'CP-01',station_name:'Trạm Quận 1',connected:true,boot_accepted:true,online:true,last_seen_at:'2026-10-02T08:00:00Z',connected_at:null,last_boot_at:null,raw_ocpp_status:null,error_code:null,vendor_error_code:null,error_at:null,vendor:'Vendor',model:'Model',firmware_version:null,connectors:[connector] }
const payload = (item = charger) => ({items:[item],page:1,total:1,total_pages:1})
describe('OcppConnectionsPage', () => {
  it('replaces full state from pushed events without manual refresh', async () => {
    vi.stubGlobal('EventSource',FakeEventSource)
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>payload()}))
    render(<OcppConnectionsPage />)
    expect(await screen.findByText('Sẵn sàng')).toBeInTheDocument()
    act(() => FakeEventSource.instances[0].onmessage?.({data:JSON.stringify(payload({...charger,connectors:[{...connector,status:'Charging'}]}))}))
    expect(screen.getByText('Đang sạc')).toBeInTheDocument()
    expect(screen.getByText(/Đang cập nhật trực tiếp/)).toBeInTheDocument()
  })
  it('reloads on reconnect, labels stale data and closes on unmount', async () => {
    vi.stubGlobal('EventSource',FakeEventSource)
    const fetchMock=vi.fn().mockResolvedValue({ok:true,json:async()=>payload()})
    vi.stubGlobal('fetch',fetchMock)
    const {unmount}=render(<OcppConnectionsPage />)
    await screen.findByText('Sẵn sàng')
    const source=FakeEventSource.instances[0]
    act(() => source.onerror?.())
    expect(screen.getByText(/Đang tự kết nối lại/)).toBeInTheDocument()
    const calls=fetchMock.mock.calls.length
    act(() => source.onopen?.())
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(calls))
    unmount();expect(source.close).toHaveBeenCalled()
  })
  it('shows offline unknown state and filters errors', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>payload({...charger,online:false,connectors:[{...connector,status:'unknown'}]})}))
    const user=userEvent.setup()
    render(<OcppConnectionsPage />)
    expect(await screen.findByText('Ngoại tuyến',{selector:'span'})).toBeInTheDocument()
    expect(screen.getAllByText('Chưa rõ trạng thái')).toHaveLength(2)
    await user.selectOptions(screen.getByLabelText('Hiển thị'),'faulted')
    expect(screen.getByText(/Không có trụ khớp/)).toBeInTheDocument()
  })
  it('supports retry after an API error', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce({ok:false,status:500}).mockResolvedValue({ok:true,json:async()=>({items:[],page:1,total:0,total_pages:0})}))
    const user=userEvent.setup()
    render(<OcppConnectionsPage />)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button',{name:'Thử lại'}))
    expect(await screen.findByText(/Chưa có trụ trong phạm vi/)).toBeInTheDocument()
  })
})
