import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StationWizard } from './StationWizard'
import { ChargerWizard } from './ChargerWizard'
import { OwnerCharging } from './OwnerCharging'
import { MockStationApi } from '../stations/api/mockStationApi'
import { MockChargePointApi } from '../chargePoints/api/mockChargePointApi'
import type { ChargePoint } from '../chargePoints/model/chargePoint'
import { ConnectionSymbol } from './OwnerVisuals'
import { Telemetry } from './OwnerWorkspace'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('approved owner flows', () => {
  it('never shows another session recovery events while history is loading or fails', async () => {
    const sessions = [71, 72].map(id => ({ id, station_name: 'Trạm thử', charge_point_code: `CP-${id}`, connector_number: 1, started_at: '2026-10-04T01:00:00Z', ended_at: null, energy_kwh: null, latest_meter_wh: null, meter_start_wh: '1000', tag_tail: 'TEST', review_reasons: [] }))
    let failHistory: (error: Error) => void = () => undefined
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/72/events')) return await new Promise<Response>((_resolve, reject) => { failHistory = reject })
      if (url.includes('/71/events')) return new Response(JSON.stringify([{ id: 'event-a', action: 'EVENT-ONLY-SESSION-A', occurred_at: '2026-10-04T02:00:00Z', details: {} }]))
      return new Response(JSON.stringify({ items: url.includes('/samples?') ? [] : sessions, page: 1, total: 2, total_pages: 1 }))
    }))
    const user = userEvent.setup()
    render(<OwnerCharging />)
    await user.click(await screen.findByRole('button', { name: /CP-71/ }))
    await user.click(screen.getByRole('button', { name: 'Lịch sử phục hồi' }))
    await screen.findByText('EVENT-ONLY-SESSION-A')
    await user.click(screen.getByRole('button', { name: 'Quay lại danh sách phiên' }))
    await user.click(await screen.findByRole('button', { name: /CP-72/ }))
    await user.click(screen.getByRole('button', { name: 'Lịch sử phục hồi' }))
    await screen.findByText('Đang tải lịch sử phục hồi…')
    expect(screen.queryByText('EVENT-ONLY-SESSION-A')).not.toBeInTheDocument()
    await act(async () => failHistory(new Error('Lỗi tải lịch sử thử nghiệm')))
    await screen.findByRole('alert')
    expect(screen.queryByText('EVENT-ONLY-SESSION-A')).not.toBeInTheDocument()
  })
  it('uses the newest sample page for a connector with many pages and warns about charging without a session', async () => {
    let open = true
    const session = { id: 43, charge_point_code: 'CP-43', connector_number: 1, started_at: '2026-10-04T01:00:00Z', latest_meter_wh: '3500', meter_start_wh: '1000' }
    const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify({ items: url.includes('/samples?') ? [{ timestamp: '2026-10-04T02:00:00Z', measurand: 'Power.Active.Import', value: '7350', unit: 'W', phase: '', location: 'Outlet' }] : open ? [session] : [], total: 201, page: 1, total_pages: url.includes('/samples?') ? 3 : 1 })))
    vi.stubGlobal('fetch', fetcher)
    const charger: ChargePoint = { id: 'cp', stationId: 's', code: 'CP-43', name: null, status: 'unknown', codeLockedAt: null, createdAt: '', updatedAt: '', connectors: [{ id: 'c', connectorNumber: 1, status: 'charging', createdAt: '', updatedAt: '' }] }
    const view = render(<Telemetry charger={charger} connector={charger.connectors[0]} reportedStatus="Charging" online onSessions={vi.fn()} />)
    await screen.findByText('7,35')
    expect(fetcher.mock.calls.some(call => call[0].includes('/samples?') && call[0].includes('page=3'))).toBe(false)
    view.unmount()
    open = false
    render(<Telemetry charger={charger} connector={charger.connectors[0]} reportedStatus="Charging" online onSessions={vi.fn()} />)
    await screen.findByText(/Trụ báo đang sạc nhưng backend chưa ghi nhận/)
    expect(screen.queryByText('7,35')).not.toBeInTheDocument()
  })
  it('retains card issuance errors until an actual retry succeeds rather than clearing them by reading the list', async () => {
    let reject = true
    const fetcher = vi.fn(async (_url: string, options?: RequestInit) => new Response(JSON.stringify(options?.method === 'POST' && reject ? { detail: 'driver_not_found' } : _url.includes('/sessions?') ? { items: [], page: 1, total_pages: 0 } : []), { status: options?.method === 'POST' && reject ? 422 : 200 }))
    vi.stubGlobal('fetch', fetcher)
    const user = userEvent.setup()
    render(<OwnerCharging />)
    await user.click(screen.getByRole('button', { name: 'Thẻ tài xế' }))
    await user.click(screen.getByRole('button', { name: 'Cấp thẻ' }))
    await user.type(screen.getByLabelText('Mã thẻ'), 'SIM-RETRY')
    await user.type(screen.getByLabelText('Email tài xế'), 'driver@example.com')
    await user.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    await user.click(screen.getByRole('button', { name: 'Cấp thẻ' }))
    await screen.findByRole('alert')
    expect(screen.queryByRole('button', { name: 'Thử lại' })).not.toBeInTheDocument()
    reject = false
    await user.click(screen.getByRole('button', { name: 'Cấp thẻ' }))
    await screen.findByText(/Đã cấp thẻ/)
    expect(fetcher.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(2)
  })
  it('opens the requested backend session even when it is outside the current list page', async () => {
    const session = { id: 64, station_name: 'Trạm thử', charge_point_code: 'CP-64', connector_number: 2, started_at: '2026-10-04T01:00:00Z', ended_at: null, energy_kwh: null, latest_meter_wh: null, meter_start_wh: '1000', tag_tail: '0064', review_reasons: [] }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify({ items: url.includes('page_size=100&state=all') ? [session] : [], page: 1, total: 1, total_pages: 1 }))))
    const opened = vi.fn()
    render(<OwnerCharging initialSessionId={64} onInitialSessionOpened={opened} />)
    await screen.findByRole('heading', { name: 'Phiên #64' })
    expect(opened).toHaveBeenCalled()
    expect(screen.getByText(/CP-64 · Đầu nối 2/)).toBeInTheDocument()
  })
  it('shows an expired active card as expired while preserving the supported lock action', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/cards') ? [{id: 'card-old', driver_email: 'driver@example.com', tag_tail: '0001', status: 'active', expires_at: '2020-01-01T00:00:00Z'}] : { items: [], page: 1, total_pages: 0 }))))
    render(<OwnerCharging />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Thẻ tài xế' }))
    await screen.findByText(/Đã hết hạn/)
    expect(screen.getByRole('button', { name: 'Khóa thẻ' })).toBeInTheDocument()
  })
  it('shows current energy and latest measurements while browsing older sample pages', async () => {
    const session = { id: 43, station_name: 'Trạm thử', charge_point_code: 'CP-43', connector_number: 1, started_at: '2026-10-04T01:00:00Z', ended_at: null, energy_kwh: null, latest_meter_wh: '3500', latest_meter_at: '2026-10-04T02:00:00Z', meter_start_wh: '1000', tag_tail: '0043', review_reasons: [], stop_reason: null }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const older = url.includes('page=2')
      const items = url.includes('/samples?') ? [{timestamp: older ? '2026-10-04T01:00:00Z' : '2026-10-04T02:00:00Z', measurand: 'Power.Active.Import', value: older ? '1000' : '2000', unit: 'W', phase: '', location: 'Outlet'}] : [session]
      return new Response(JSON.stringify({ items, total: url.includes('/samples?') ? 101 : 1, page: older ? 2 : 1, total_pages: url.includes('/samples?') ? 2 : 1 }))
    }))
    const user = userEvent.setup()
    render(<OwnerCharging />)
    await user.click(await screen.findByRole('button', { name: /CP-43/ }))
    await waitFor(() => expect(screen.getByLabelText('Số đo mới nhất')).toHaveTextContent('2 kW'))
    expect(screen.getByText('2,5 kWh')).toBeInTheDocument()
    expect(screen.queryByText('Điện năng chốt')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Sau' }))
    await screen.findByText('1.000 W')
    expect(screen.getByLabelText('Số đo mới nhất')).toHaveTextContent('2 kW')
  })
  it('refreshes final session facts even after closure removes it from the open filter', async () => {
    let closed = false
    const timers: (() => void)[] = []
    vi.spyOn(window, 'setInterval').mockImplementation((callback) => {
      timers.push(callback as () => void)
      return timers.length
    })
    const session = { id: 42, station_name: 'Trạm thử', charge_point_code: 'CP-42', connector_number: 1, started_at: '2026-10-04T01:00:00Z', ended_at: null, energy_kwh: null, latest_meter_wh: null, latest_meter_at: null, meter_start_wh: '1000', tag_tail: '0042', review_reasons: [], stop_reason: null }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const final = { ...session, ended_at: '2026-10-04T02:00:00Z', energy_kwh: '12.5', review_reasons: ['meter_missing'] }
      const items = url.includes('/samples?') ? [] : closed && url.includes('state=open') ? [] : [closed ? final : session]
      return new Response(JSON.stringify({ items, total: items.length, page: 1, total_pages: items.length ? 1 : 0 }))
    }))
    const user = userEvent.setup()
    render(<OwnerCharging />)
    await user.selectOptions(screen.getByLabelText('Trạng thái'), 'open')
    await user.click(await screen.findByRole('button', { name: /CP-42/ }))
    expect(screen.getByText('Đang mở')).toBeInTheDocument()
    closed = true
    await act(async () => { timers.forEach(callback => callback()) })
    await waitFor(() => expect(screen.getByText('12,5 kWh')).toBeInTheDocument())
    expect(screen.queryByText('Đang mở')).not.toBeInTheDocument()
    expect(screen.getByText(/Cần kiểm tra/)).toBeInTheDocument()
  })

  it('provides non-color and accessible connection cues for all three states', () => {
    const { rerender } = render(<ConnectionSymbol online />)
    const onlineShape = screen.getByRole('img', { name: 'Trực tuyến' }).innerHTML
    rerender(<ConnectionSymbol online={false} />)
    const offlineShape = screen.getByRole('img', { name: 'Ngoại tuyến' }).innerHTML
    expect(offlineShape).not.toBe(onlineShape)
    rerender(<ConnectionSymbol />)
    expect(screen.getByRole('img', { name: 'Chưa có dữ liệu kết nối' }).innerHTML).not.toBe(offlineShape)
  })
  it('retains a created station after upload failure and retries only its photo', async () => {
    const NativeURL = URL
    vi.stubGlobal(
      'URL',
      Object.assign(class extends NativeURL {}, {
        createObjectURL: () => 'blob:owner-test',
        revokeObjectURL: vi.fn(),
      }),
    )
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: 'invalid_station_photo' }), {
          status: 422,
        }),
      )
      .mockResolvedValueOnce(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    const api = new MockStationApi([], 0)
    const create = vi.spyOn(api, 'createStation')
    const onSaved = vi.fn()
    const user = userEvent.setup()
    render(<StationWizard api={api} onCancel={vi.fn()} onSaved={onSaved} />)
    await user.type(screen.getByLabelText('Tên trạm'), 'Trạm mới')
    await user.type(screen.getByLabelText('Địa chỉ'), 'Địa chỉ thử')
    await user.type(screen.getByLabelText('Vĩ độ'), '10.8')
    await user.type(screen.getByLabelText('Kinh độ'), '106.7')
    await user.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    await user.upload(
      screen.getByLabelText('Chọn ảnh'),
      new File([new Uint8Array([137,80,78,71,13,10,26,10])], 'station.jpg', { type: 'image/jpeg' }),
    )
    await user.click(screen.getByRole('button', { name: 'Tạo trạm' }))
    await screen.findByRole('alert')
    expect(create).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0][1]?.headers).toEqual({ 'Content-Type': 'image/png' })
    expect(onSaved).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Tạo trạm' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
    expect(create).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0][1]?.headers).toEqual({ 'Content-Type': 'image/png' })
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(fetcher.mock.calls[0][0]).toBe(fetcher.mock.calls[1][0])
    expect(fetcher.mock.calls[1][1]).toMatchObject({
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'image/png' },
    })
  })

  it('saves name and connector metadata without sending a locked charger code', async () => {
    const charger: ChargePoint = {
      id: 'charger-locked',
      stationId: 'station-one',
      code: 'CP-LOCKED',
      name: 'Tên cũ',
      status: 'unknown',
      codeLockedAt: '2026-10-04T00:00:00Z',
      createdAt: '',
      updatedAt: '',
      connectors: [
        {
          id: 'connector-one',
          connectorNumber: 1,
          status: 'unknown',
          createdAt: '',
          updatedAt: '',
        },
      ],
    }
    const api = new MockChargePointApi([charger], 0)
    const update = vi.spyOn(api, 'updateChargePoint')
    const onSaved = vi.fn()
    const user = userEvent.setup()
    render(
      <ChargerWizard
        stationId={charger.stationId}
        charger={charger}
        api={api}
        onCancel={vi.fn()}
        onSaved={onSaved}
      />,
    )
    expect(screen.getByLabelText('Mã trụ')).toBeDisabled()
    await user.clear(screen.getByLabelText('Tên hiển thị · tùy chọn'))
    await user.type(
      screen.getByLabelText('Tên hiển thị · tùy chọn'),
      'Trụ sân trước',
    )
    await user.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    await user.selectOptions(screen.getByLabelText('Loại đầu nối'), 'CCS2')
    await user.selectOptions(screen.getByLabelText('Loại dòng điện'), 'DC')
    await user.type(screen.getByLabelText('Công suất (kW)'), '60')
    await user.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    await user.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
    expect(update.mock.calls[0][1]).not.toHaveProperty('code')
    expect(update.mock.calls[0][1]).toMatchObject({
      name: 'Trụ sân trước',
      connectors: [
        {
          connector_number: 1,
          connector_type: 'CCS2',
          current_type: 'DC',
          max_power_kw: '60',
        },
      ],
    })
  })

  it('issues a card only after review, using the manually entered simulator tag', async () => {
    const fetcher = vi.fn(
      async (_url: string, options?: RequestInit) =>
        new Response(
          JSON.stringify(
            options?.method === 'POST'
              ? { id: 'new-card' }
              : String(_url).includes('/sessions?')
                ? { items: [], total: 0, page: 1, total_pages: 0 }
                : [],
          ),
        ),
    )
    vi.stubGlobal('fetch', fetcher)
    const user = userEvent.setup()
    render(<OwnerCharging />)
    await user.click(screen.getByRole('button', { name: 'Thẻ tài xế' }))
    await user.click(screen.getByRole('button', { name: 'Cấp thẻ' }))
    await user.type(screen.getByLabelText('Mã thẻ'), 'SIM-CARD-01')
    await user.type(screen.getByLabelText('Email tài xế'), 'driver@example.com')
    await user.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    expect(
      fetcher.mock.calls.filter((call) => call[1]?.method === 'POST'),
    ).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: 'Cấp thẻ' }))
    await screen.findByText(/Đã cấp thẻ/)
    const write = fetcher.mock.calls.find((call) => call[1]?.method === 'POST')
    expect(write?.[0]).toBe('/api/v1/charging/cards')
    expect(JSON.parse(String(write?.[1]?.body))).toEqual({
      id_tag: 'SIM-CARD-01',
      driver_email: 'driver@example.com',
      expires_at: null,
    })
    expect(
      screen.queryByRole('button', { name: /Dừng từ xa|Reset|Đóng phiên/ }),
    ).not.toBeInTheDocument()
  })
})
