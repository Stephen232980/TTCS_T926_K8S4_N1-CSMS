import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DriverSessionControls } from './DriverSessionControls'

beforeEach(() => { sessionStorage.clear() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
const ok = (status = 'Accepted') => new Response(JSON.stringify({ id: 'command-1', status }), { status: 200 })

describe('Driver session controls', () => {
  it('requires confirmation and submits one stop request on a double click', async () => {
    const fetcher = vi.fn().mockResolvedValue(ok())
    vi.stubGlobal('fetch', fetcher)
    render(<DriverSessionControls session={{ id: 72 }} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Dừng sạc' }))
    expect(fetcher).not.toHaveBeenCalled()
    const confirm = screen.getByRole('button', { name: 'Xác nhận dừng sạc' })
    fireEvent.click(confirm); fireEvent.click(confirm)
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
    expect(fetcher.mock.calls[0][0]).toContain('/sessions/72/stop')
    expect(screen.queryByRole('button', { name: /Mô phỏng/ })).not.toBeInTheDocument()
    await screen.findByText('Trụ đã nhận yêu cầu. Đang chờ tín hiệu thực tế từ trụ.')
  })

  it('does not send a command or settle when the driver confirms unplugging', () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
    render(<DriverSessionControls session={{ id: 72, ended_at: '2026-10-13T12:00:00Z' }} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Tôi đã rút súng khỏi xe' }))
    expect(fetcher).not.toHaveBeenCalled()
    expect(screen.getByText('Đã ghi nhận xác nhận của bạn. CSMS vẫn chờ tín hiệu rút súng từ trụ.')).toBeInTheDocument()
  })

  it('shows and submits simulator unplug only when the server allows demo', async () => {
    const fetcher = vi.fn().mockResolvedValue(ok()); vi.stubGlobal('fetch', fetcher)
    render(<DriverSessionControls session={{ id: 73, demo_unplug_available: true }} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Mô phỏng rút súng · Demo' }))
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
    expect(fetcher.mock.calls[0][0]).toContain('/sessions/73/demo-unplug')
    expect(JSON.parse(fetcher.mock.calls[0][1].body).request_id).toBeTruthy()
  })

  it('reuses the key after a lost response rather than issuing a second intent', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('Mất kết nối')).mockResolvedValueOnce(ok())
    vi.stubGlobal('fetch', fetcher)
    render(<DriverSessionControls session={{ id: 74 }} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Dừng sạc' }))
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận dừng sạc' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Kiểm tra lại yêu cầu' }))
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
    expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body)
  })

  it('creates a new intent only after an explicit retry of a rejected stop', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(ok('Rejected')).mockResolvedValueOnce(ok())
    vi.stubGlobal('fetch', fetcher)
    render(<DriverSessionControls session={{ id: 75 }} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Dừng sạc' }))
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận dừng sạc' }))
    await screen.findByText('Trụ từ chối yêu cầu. Hãy kiểm tra thiết bị hoặc liên hệ vận hành.')
    expect(fetcher).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Dừng sạc' }))
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận dừng sạc' }))
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
    expect(fetcher.mock.calls[0][1].body).not.toBe(fetcher.mock.calls[1][1].body)
  })
})
