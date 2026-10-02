import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { AuthApiError, type AuthApi } from './features/auth/api/authApi'
import type { AuthenticatedUser } from './features/auth/model/auth'
import { SESSION_UNAUTHORIZED_EVENT } from './features/auth/sessionEvents'
import { MockStationApi } from './features/stations/api/mockStationApi'
import { MockChargePointApi } from './features/chargePoints/api/mockChargePointApi'

const owner: AuthenticatedUser = {
  id: 'a4e67f4a-1c6c-4dfa-a01d-581b624749af',
  email: 'owner@example.com',
  roles: ['station_owner'],
}

class AppAuthApi implements AuthApi {
  currentUser: AuthenticatedUser | null

  constructor(currentUser: AuthenticatedUser | null) {
    this.currentUser = currentUser
  }

  async login(): Promise<void> {
    this.currentUser = owner
  }

  async logout(): Promise<void> {
    this.currentUser = null
  }

  async getCurrentUser(): Promise<AuthenticatedUser> {
    if (this.currentUser === null) throw new AuthApiError(401)
    return this.currentUser
  }
}

describe('App', () => {
  it.each([
    [['operator'], false],
    [['admin'], false],
    [['station_owner'], true],
    [['driver', 'station_owner'], true],
  ])('applies write permissions through station details for %s', async (roles, canWrite) => {
    const user = userEvent.setup()
    render(<App authApi={new AppAuthApi({ ...owner, roles })}
      stationApi={new MockStationApi(undefined, 0)} chargePointApi={new MockChargePointApi([], 0)} />)
    await screen.findByRole('heading', { name: 'Trạm sạc' })
    expect(screen.getByRole('link', { name: 'Trạm sạc' })).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Xem chi tiết Trạm Quận 1' }))
    await screen.findByRole('heading', { name: 'Trạm Quận 1' })
    expect(screen.queryByRole('heading', { name: 'Thêm trụ sạc' }) !== null).toBe(canWrite)
  })

  it.each([
    ['station_owner', 'Trạm sạc'],
    ['operator', 'Trạm sạc'],
    ['admin', 'Trạm sạc'],
    ['driver', 'Tìm trạm sạc'],
    ['accountant', 'Phiên sạc'],
  ])('routes the %s role to its permitted screen', async (role, heading) => {
    const stationApi = new MockStationApi(undefined, 0)
    const listStations = vi.spyOn(stationApi, 'listStations')
    render(
      <App
        authApi={new AppAuthApi({ ...owner, roles: [role] })}
        stationApi={stationApi}
      />,
    )

    expect(
      await screen.findByRole('heading', { name: heading }),
    ).toBeInTheDocument()
    if (role === 'driver' || role === 'accountant') {
      expect(listStations).not.toHaveBeenCalled()
    } else {
      await waitFor(() => expect(listStations).toHaveBeenCalled())
    }
    if (role === 'operator' || role === 'admin') {
      expect(screen.queryByRole('button', { name: /Chỉnh sửa/ })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Tạo trạm' })).not.toBeInTheDocument()
    }
  })

  it('loads and filters an injected station API', async () => {
    const user = userEvent.setup()
    render(
      <App
        authApi={new AppAuthApi(owner)}
        stationApi={new MockStationApi()}
      />,
    )

    expect(
      await screen.findByRole('heading', { name: 'Trạm sạc' }),
    ).toBeInTheDocument()
    expect(await screen.findAllByText('Trạm Quận 1')).toHaveLength(2)

    await user.type(screen.getByRole('searchbox', { name: 'Tìm trạm' }), 'Thủ Đức')

    expect(await screen.findAllByText('Trạm Thủ Đức')).toHaveLength(2)
    await waitFor(() => {
      expect(screen.queryAllByText('Trạm Quận 1')).toHaveLength(0)
    })
  })

  it('opens a station detail page and returns to the list', async () => {
    const user = userEvent.setup()
    render(
      <App
        authApi={new AppAuthApi(owner)}
        stationApi={new MockStationApi(undefined, 0)}
      />,
    )

    await user.click(
      await screen.findByRole('button', { name: 'Xem chi tiết Trạm Quận 1' }),
    )

    expect(
      await screen.findByRole('heading', { name: 'Trạm Quận 1' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Quay lại danh sách trạm' }))
    expect(
      await screen.findByRole('heading', { name: 'Trạm sạc' }),
    ).toBeInTheDocument()
  })

  it('shows login without a valid session and enters the app after login', async () => {
    const user = userEvent.setup()
    const authApi = new AppAuthApi(null)
    render(<App authApi={authApi} stationApi={new MockStationApi()} />)

    expect(
      await screen.findByRole('heading', { name: 'Đăng nhập' }),
    ).toBeInTheDocument()
    await user.type(screen.getByLabelText('Email'), 'owner@example.com')
    await user.type(screen.getByLabelText('Mật khẩu'), 'mat-khau-dung')
    await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))

    expect(
      await screen.findByRole('heading', { name: 'Trạm sạc' }),
    ).toBeInTheDocument()
    expect(screen.getByText('owner@example.com')).toBeInTheDocument()
  })

  it('returns to login when an API reports an expired session', async () => {
    render(
      <App
        authApi={new AppAuthApi(owner)}
        stationApi={new MockStationApi()}
      />,
    )
    expect(
      await screen.findByRole('heading', { name: 'Trạm sạc' }),
    ).toBeInTheDocument()

    window.dispatchEvent(new Event(SESSION_UNAUTHORIZED_EVENT))

    expect(
      await screen.findByRole('heading', { name: 'Đăng nhập' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.',
    )
  })

  it('logs out and returns to the login page', async () => {
    const user = userEvent.setup()
    const authApi = new AppAuthApi(owner)
    render(<App authApi={authApi} stationApi={new MockStationApi()} />)

    await user.click(await screen.findByRole('button', { name: 'Đăng xuất' }))

    expect(
      await screen.findByRole('heading', { name: 'Đăng nhập' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Bạn đã đăng xuất an toàn.',
    )
    expect(authApi.currentUser).toBeNull()
  })
})
