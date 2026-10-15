import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DriverMapPage } from './DriverMapPage'

vi.mock('../../components/maps/StationMap', () => ({ StationMap: ({ onLocate }: { onLocate?: (position: { latitude: number; longitude: number }) => void }) => <div aria-label="Bản đồ trạm sạc"><button onClick={() => onLocate?.({ latitude: 10.7, longitude: 106.7 })}>Đến vị trí của tôi</button></div> }))
vi.mock('./DriverCharging', () => ({ DriverCharging: () => <div /> }))
afterEach(() => vi.unstubAllGlobals())
const data = { items: [{ id: 'one', name: 'Trạm thật', address: 'Địa chỉ trạm', latitude: 10.7, longitude: 106.7 }], page: 1, total: 1, total_pages: 1 }
describe('DriverMapPage', () => {
  it('retains the last projection with a stale warning after a visible refresh fails', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ ...data, items: [{ ...data.items[0], available_connectors: 1, total_connectors: 2, energy_rate_vnd_per_kwh: 2500 }] }) }).mockResolvedValue({ ok: false, status: 500 })
    vi.stubGlobal('fetch', fetchMock)
    render(<DriverMapPage onOpenStation={vi.fn()} />)
    expect(await screen.findByText('1/2 đầu nối rảnh')).toBeInTheDocument()
    expect(screen.getByText('2.500 đ/kWh')).toBeInTheDocument()
    fireEvent(document, new Event('visibilitychange'))
    expect(await screen.findByRole('alert')).toHaveTextContent('có thể cũ')
    expect(screen.getByText('Trạm thật')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Xem đầu nối' })).toBeDisabled()
  })
  it('bounds broad search without fetching or sorting partial pages', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], page: 1, total: 501, total_pages: 6, search_too_broad: true }) })
    vi.stubGlobal('fetch', request)
    render(<DriverMapPage />)
    expect(await screen.findByText(/Có hơn 500 trạm/)).toBeInTheDocument()
    expect(request).toHaveBeenCalledOnce()
    expect(screen.queryByLabelText('Danh sách trạm trên bản đồ')).not.toBeInTheDocument()
  })
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
  it('sorts the complete result by distance only after browser location, without sending coordinates to the API', async () => {
    const far = { id: 'far', name: 'Trạm xa', address: 'Xa', latitude: 11.7, longitude: 106.7 }
    const fetchMock = vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes('page=2') ? { ...data, page: 2, total: 2, total_pages: 2 } : { ...data, items: [far], total: 2, total_pages: 2 } }))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<DriverMapPage />)
    expect(await screen.findByText('Trạm thật')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { pressed: false }).map(button => button.textContent)).toEqual(['Trạm xaXa', 'Trạm thậtĐịa chỉ trạm'])
    await user.click(screen.getByRole('button', { name: 'Đến vị trí của tôi' }))
    expect(screen.getByRole('heading', { name: 'Trạm gần bạn' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { pressed: false })[0]).toHaveTextContent('Trạm thật')
    expect(screen.getByText('0 km')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls.every(([url]) => !url.includes('latitude') && !url.includes('longitude'))).toBe(true)
  })
})
