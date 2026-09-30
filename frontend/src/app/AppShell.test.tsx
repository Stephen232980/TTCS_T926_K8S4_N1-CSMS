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
        onUnavailableNavigation={() => undefined}
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

  it('reports unavailable settings and account actions', async () => {
    const user = userEvent.setup()
    const onUnavailableNavigation = vi.fn()
    render(
      <AppShell
        currentUser={currentUser}
        onUnavailableNavigation={onUnavailableNavigation}
      >
        <p>Nội dung</p>
      </AppShell>,
    )

    await user.click(screen.getByRole('link', { name: 'Cài đặt' }))
    await user.click(screen.getByRole('button', { name: 'Mở tài khoản' }))

    expect(onUnavailableNavigation).toHaveBeenNthCalledWith(1, 'Cài đặt')
    expect(onUnavailableNavigation).toHaveBeenNthCalledWith(2, 'Tài khoản')
  })
})
