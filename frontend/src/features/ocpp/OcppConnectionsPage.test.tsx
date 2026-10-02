import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OcppConnectionsPage } from './OcppConnectionsPage'

afterEach(() => vi.unstubAllGlobals())
const charger = { id: 'one', code: 'CP-01', station_name: 'Trạm Quận 1', connected: true, boot_accepted: false, connected_at: '2026-10-02T08:00:00Z', last_boot_at: null, vendor: null, model: null, firmware_version: null }
describe('OcppConnectionsPage', () => {
  it('distinguishes socket connection from boot approval and refreshes', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ok: true, json: async () => ({items:[charger], page:1,total:1,total_pages:1})}).mockResolvedValue({ok:true,json:async()=>({items:[{...charger,boot_accepted:true,vendor:'Vendor'}],page:1,total:1,total_pages:1})})
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<OcppConnectionsPage />)
    expect(await screen.findByText('Đã kết nối · Chưa được chấp nhận khởi động')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/ocpp/connections'),expect.objectContaining({credentials:'include'}))
    await user.click(screen.getByRole('button',{name:'Làm mới'}))
    expect(await screen.findByText('Đã chấp nhận khởi động')).toBeInTheDocument()
    expect(screen.getByText('Vendor')).toBeInTheDocument()
  })
  it('shows an error and supports retry', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce({ok:false,status:500}).mockResolvedValue({ok:true,json:async()=>({items:[],page:1,total:0,total_pages:0})}))
    const user=userEvent.setup()
    render(<OcppConnectionsPage />)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button',{name:'Thử lại'}))
    expect(await screen.findByText(/Chưa có trụ trong phạm vi/)).toBeInTheDocument()
  })
})
