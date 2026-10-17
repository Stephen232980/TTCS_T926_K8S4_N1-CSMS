import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { StationPowerScheduleEditor } from './StationPowerScheduleEditor'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('renders confirmed compliance badge when applied limit matches schedule', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/power-schedule/current')) {
        return new Response(
          JSON.stringify({
            station_id: 'st-1',
            timezone: 'Asia/Ho_Chi_Minh',
            local_time: '22:00',
            local_date: '2026-10-17',
            power_limit_w: 15000,
            power_limit_kw: '15.000',
            scheduled_limit_w: 15000,
            scheduled_limit_kw: '15.000',
            applied_limit_w: 15000,
            applied_limit_kw: '15.000',
            confirmed_limit_w: 15000,
            confirmed_limit_kw: '15.000',
            compliance_status: 'confirmed',
            state: 'ready',
            issue: null,
          }),
        )
      }
      return new Response(JSON.stringify(null), { status: 404 })
    }),
  )

  render(<StationPowerScheduleEditor stationId="st-1" />)
  const badge = await screen.findByTestId('compliance-badge')
  expect(badge).toHaveTextContent('Đã xác nhận tuân thủ: 15.000 kW')
  expect(screen.queryByTestId('compliance-degraded-warning')).not.toBeInTheDocument()
})

it('renders applying badge when schedule reduced but chargers still at previous limit', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/power-schedule/current')) {
        return new Response(
          JSON.stringify({
            station_id: 'st-1',
            timezone: 'Asia/Ho_Chi_Minh',
            local_time: '22:00',
            local_date: '2026-10-17',
            power_limit_w: 15000,
            power_limit_kw: '15.000',
            scheduled_limit_w: 15000,
            scheduled_limit_kw: '15.000',
            applied_limit_w: 30000,
            applied_limit_kw: '30.000',
            confirmed_limit_w: 30000,
            confirmed_limit_kw: '30.000',
            compliance_status: 'applying',
            state: 'applying',
            issue: null,
          }),
        )
      }
      return new Response(JSON.stringify(null), { status: 404 })
    }),
  )

  render(<StationPowerScheduleEditor stationId="st-1" />)
  const badge = await screen.findByTestId('compliance-badge')
  expect(badge).toHaveTextContent('Chờ áp dụng: Lịch 15.000 kW (Đã xác nhận: 30.000 kW)')
  expect(badge).not.toHaveTextContent('Đã xác nhận tuân thủ: 15.000 kW')
})

it('renders degraded badge and warning alert when chargers fail to reduce', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/power-schedule/current')) {
        return new Response(
          JSON.stringify({
            station_id: 'st-1',
            timezone: 'Asia/Ho_Chi_Minh',
            local_time: '22:00',
            local_date: '2026-10-17',
            power_limit_w: 15000,
            power_limit_kw: '15.000',
            scheduled_limit_w: 15000,
            scheduled_limit_kw: '15.000',
            applied_limit_w: 30000,
            applied_limit_kw: '30.000',
            confirmed_limit_w: 30000,
            confirmed_limit_kw: '30.000',
            compliance_status: 'degraded',
            state: 'degraded',
            issue: 'power_profile_not_verified',
          }),
        )
      }
      return new Response(JSON.stringify(null), { status: 404 })
    }),
  )

  render(<StationPowerScheduleEditor stationId="st-1" />)
  const badge = await screen.findByTestId('compliance-badge')
  expect(badge).toHaveTextContent('Suy giảm / Chưa tuân thủ: Lịch 15.000 kW (Chưa xác nhận giảm từ 30.000 kW)')
  expect(await screen.findByTestId('compliance-degraded-warning')).toBeInTheDocument()
})
