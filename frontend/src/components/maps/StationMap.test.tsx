import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import L from 'leaflet'
import { StationMap } from './StationMap'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function locationMock() {
  const getCurrentPosition = vi.fn<Geolocation['getCurrentPosition']>()
  vi.stubGlobal('navigator', Object.assign(Object.create(navigator), { geolocation: { getCurrentPosition } }))
  return getCurrentPosition
}

describe('StationMap geolocation', () => {
  it.each([
    [1, 'Quyền định vị bị chặn.'],
    [2, 'Thiết bị chưa cung cấp được vị trí hiện tại.'],
    [3, 'Hết thời gian chờ vị trí.'],
  ])('explains error %s and allows retry without blocking manual selection', (code, message) => {
    const locate = locationMock()
    const pick = vi.fn()
    render(<StationMap onPick={pick} />)
    fireEvent.click(screen.getByRole('button', { name: 'Đến vị trí của tôi' }))
    expect(screen.getByRole('button', { name: 'Đang lấy vị trí…' })).toBeDisabled()
    act(() => locate.mock.calls[0][1]?.({ code, message: 'provider error' } as GeolocationPositionError))
    expect(screen.getByRole('status')).toHaveTextContent(message)
    fireEvent.click(screen.getByRole('button', { name: 'Chọn tâm bản đồ' }))
    expect(pick).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: 'Đến vị trí của tôi' }))
    expect(locate).toHaveBeenCalledTimes(2)
  })

  it('moves the map after success without changing the saved station position', () => {
    const locate = locationMock()
    const setView = vi.spyOn(L.Map.prototype, 'setView')
    const pick = vi.fn()
    render(<StationMap onPick={pick} />)
    fireEvent.click(screen.getByRole('button', { name: 'Đến vị trí của tôi' }))
    act(() => locate.mock.calls[0][0]({ coords: { latitude: 10.7, longitude: 106.7 } } as GeolocationPosition))
    expect(setView).toHaveBeenLastCalledWith([10.7, 106.7], 15)
    expect(pick).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Đến vị trí của tôi' })).toBeEnabled()
  })

  it('ignores a pending response after leaving the page', () => {
    const locate = locationMock()
    const view = render(<StationMap />)
    fireEvent.click(screen.getByRole('button', { name: 'Đến vị trí của tôi' }))
    view.unmount()
    const setView = vi.spyOn(L.Map.prototype, 'setView')
    act(() => locate.mock.calls[0][0]({ coords: { latitude: 10.7, longitude: 106.7 } } as GeolocationPosition))
    expect(setView).not.toHaveBeenCalled()
  })
})
