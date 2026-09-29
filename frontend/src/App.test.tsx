import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import App from './App'
import { AuthApiError, type AuthApi } from './features/auth/api/authApi'
import type { AuthenticatedUser } from './features/auth/model/auth'
import { SESSION_UNAUTHORIZED_EVENT } from './features/auth/sessionEvents'
import { MockStationApi } from './features/stations/api/mockStationApi'

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

  async getCurrentUser(): Promise<AuthenticatedUser> {
    if (this.currentUser === null) throw new AuthApiError(401)
    return this.currentUser
  }
}

describe('App', () => {
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
    expect(screen.queryAllByText('Trạm Quận 1')).toHaveLength(0)
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
})
