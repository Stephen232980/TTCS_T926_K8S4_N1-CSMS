import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DriverMapPage } from './DriverMapPage'

vi.mock('../../components/maps/StationMap', () => ({ StationMap: () => <div aria-label="Bản đồ trạm sạc" /> }))
vi.mock('./DriverCharging', () => ({ DriverCharging: () => <div /> }))
afterEach(() => vi.unstubAllGlobals())
const data = { items: [{ id: 'one', name: 'Trạm thật', address: 'Địa chỉ trạm', latitude: 10.7, longitude: 106.7 }], page: 1, total: 1, total_pages: 1 }
describe('DriverMapPage', () => {
  it('loads the driver endpoint with a session and searches by address', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => data })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<DriverMapPage />)
    expect(await screen.findByText('Trạm thật')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/driver/stations?'), expect.objectContaining({ credentials: 'include' }))
    await user.type(screen.getByLabelText('Tên trạm hoặc địa chỉ'), 'Quận 1')
    await user.click(screen.getByRole('button', { name: 'Tìm trạm' }))
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining('search=Qu%E1%BA%ADn+1'), expect.anything()))
  })
  it('lets the user retry a failed request', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: false, status: 500 }).mockResolvedValue({ ok: true, json: async () => data })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<DriverMapPage />)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('Trạm thật')).toBeInTheDocument()
  })
})
