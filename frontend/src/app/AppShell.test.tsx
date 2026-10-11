import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'

const currentUser = {
  id: 'owner-1',
  email: 'owner@example.com',
  roles: ['station_owner'],
}

describe('AppShell', () => {
  it('exposes and closes mobile navigation accessibly', async () => {
    const user = userEvent.setup()
    render(
      <AppShell
        currentUser={currentUser}
        onLogout={async () => undefined}
      >
        <p>Nội dung</p>
      </AppShell>,
    )

    const menuButton = screen.getByRole('button', { name: 'Mở điều hướng' })
    expect(menuButton).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('link', { name: 'Trạm sạc' })).toHaveAttribute(
      'aria-current',
      'page',
    )

    await user.click(menuButton)
    expect(
      screen.getByRole('button', { name: 'Đóng điều hướng' }),
    ).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'CSMS - Trang chủ' })).toHaveFocus()
    expect(document.body).toHaveStyle({ overflow: 'hidden' })

    await user.keyboard('{Escape}')
    expect(
      screen.getByRole('button', { name: 'Mở điều hướng' }),
    ).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('button', { name: 'Mở điều hướng' })).toHaveFocus()
    expect(document.body.style.overflow).toBe('')
  })

  it('shows working navigation and the full account email', () => {
    const longEmailUser = {
      ...currentUser,
      email: 'owner.demo.20261001@example.com',
    }
    render(
      <AppShell
        currentUser={longEmailUser}
        onLogout={async () => undefined}
      >
        <p>Nội dung</p>
      </AppShell>,
    )

    expect(screen.getAllByRole('link')).toHaveLength(2)
    expect(screen.getByRole('link', { name: 'Trạm sạc' })).toBeInTheDocument()
    expect(screen.queryByText('Tổng quan')).not.toBeInTheDocument()
    expect(screen.queryByText('Cài đặt')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mở tài khoản' })).not.toBeInTheDocument()
    expect(screen.getByTitle(longEmailUser.email)).toHaveTextContent(
      longEmailUser.email,
    )
  })

  it.each([
    ['driver', 'Khu vực tài xế'],
    ['accountant', 'Khu vực kế toán'],
  ])('shows the %s navigation scope', (role, label) => {
    render(
      <AppShell
        currentUser={{ ...currentUser, roles: [role] }}
        onLogout={async () => undefined}
      >
        <p>Nội dung</p>
      </AppShell>,
    )

    expect(screen.getByRole('link', { name: label })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('keeps the session and reports a failed logout', async () => {
    const user = userEvent.setup()
    const onLogout = vi.fn().mockRejectedValue(new Error('network error'))
    render(
      <AppShell currentUser={currentUser} onLogout={onLogout}>
        <p>Nội dung</p>
      </AppShell>,
    )

    await user.click(screen.getByRole('button', { name: 'Đăng xuất' }))

    expect(onLogout).toHaveBeenCalledOnce()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Không thể đăng xuất. Vui lòng kiểm tra kết nối và thử lại.',
    )
    expect(screen.getByRole('button', { name: 'Đăng xuất' })).toBeEnabled()
  })
})
