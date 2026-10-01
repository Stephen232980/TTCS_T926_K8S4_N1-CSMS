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
  it.each([{ roles: [] }, { roles: ['unknown'] }])('hides station navigation for unrecognized roles ($roles)', ({ roles }) => {
    render(<AppShell currentUser={{ ...currentUser, roles }} onLogout={async () => undefined}>Nội dung</AppShell>)
    expect(screen.queryByRole('link', { name: 'Trạm sạc' })).not.toBeInTheDocument()
  })

  it('uses station navigation when a later role permits station access', () => {
    render(<AppShell currentUser={{ ...currentUser, roles: ['driver', 'station_owner'] }} onLogout={async () => undefined}>Nội dung</AppShell>)
    expect(screen.getByRole('link', { name: 'Trạm sạc' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Khu vực tài xế' })).not.toBeInTheDocument()
  })

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

  it('shows only working navigation and exposes the full account email', () => {
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
    expect(screen.queryByText('Tổng quan')).not.toBeInTheDocument()
    expect(screen.queryByText('Cài đặt')).not.toBeInTheDocument()
    expect(screen.getByTitle(longEmailUser.email)).toHaveTextContent(
      longEmailUser.email,
    )
    expect(
      screen.getByLabelText(`Tài khoản ${longEmailUser.email}`),
    ).toBeInTheDocument()
  })

  it('disables logout while pending and reports a failure', async () => {
    const user = userEvent.setup()
    const onLogout = vi.fn().mockRejectedValue(new Error('network error'))
    render(
      <AppShell
        currentUser={currentUser}
        onLogout={onLogout}
      >
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
