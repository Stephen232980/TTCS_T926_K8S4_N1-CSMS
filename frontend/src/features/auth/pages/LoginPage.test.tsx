import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AuthApiError, type AuthApi } from '../api/authApi'
import type { AuthenticatedUser, LoginInput } from '../model/auth'
import { LoginPage } from './LoginPage'

class LoginTestApi implements AuthApi {
  login = vi.fn<(input: LoginInput) => Promise<void>>()

  async getCurrentUser(): Promise<AuthenticatedUser> {
    throw new Error('Not used by LoginPage')
  }
}

describe('LoginPage', () => {
  it('shows field errors without calling the API', async () => {
    const user = userEvent.setup()
    const api = new LoginTestApi()
    render(<LoginPage api={api} onAuthenticated={() => undefined} />)

    await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))

    expect(screen.getByText('Vui lòng nhập email.')).toBeInTheDocument()
    expect(screen.getByText('Vui lòng nhập mật khẩu.')).toBeInTheDocument()
    expect(api.login).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Email')).toHaveFocus()
  })

  it('submits valid credentials once and reports success', async () => {
    const user = userEvent.setup()
    const api = new LoginTestApi()
    api.login.mockResolvedValue()
    const onAuthenticated = vi.fn()
    render(<LoginPage api={api} onAuthenticated={onAuthenticated} />)

    await user.type(screen.getByLabelText('Email'), 'owner@example.com')
    await user.type(screen.getByLabelText('Mật khẩu'), 'mat-khau-dung')
    await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))

    expect(api.login).toHaveBeenCalledTimes(1)
    expect(api.login).toHaveBeenCalledWith({
      email: 'owner@example.com',
      password: 'mat-khau-dung',
    })
    expect(onAuthenticated).toHaveBeenCalledTimes(1)
  })

  it('shows the generic invalid-credentials message', async () => {
    const user = userEvent.setup()
    const api = new LoginTestApi()
    api.login.mockRejectedValue(new AuthApiError(401, 'backend detail'))
    render(<LoginPage api={api} onAuthenticated={() => undefined} />)

    await user.type(screen.getByLabelText('Email'), 'owner@example.com')
    await user.type(screen.getByLabelText('Mật khẩu'), 'sai')
    await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Email hoặc mật khẩu không đúng.',
    )
  })

  it('explains the temporary lock without exposing account details', async () => {
    const user = userEvent.setup()
    const api = new LoginTestApi()
    api.login.mockRejectedValue(new AuthApiError(423))
    render(<LoginPage api={api} onAuthenticated={() => undefined} />)

    await user.type(screen.getByLabelText('Email'), 'owner@example.com')
    await user.type(screen.getByLabelText('Mật khẩu'), 'mat-khau-dung')
    await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Đăng nhập tạm thời bị khóa. Vui lòng thử lại sau 15 phút.',
    )
  })
})
