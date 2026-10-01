import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
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
      <AppShell currentUser={currentUser}>
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

  it('shows only working navigation for the current role', () => {
    render(
      <AppShell currentUser={currentUser}>
        <p>Nội dung</p>
      </AppShell>,
    )

    expect(screen.getAllByRole('link')).toHaveLength(2)
    expect(screen.getByRole('link', { name: 'Trạm sạc' })).toBeInTheDocument()
    expect(screen.queryByText('Tổng quan')).not.toBeInTheDocument()
    expect(screen.queryByText('Cài đặt')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mở tài khoản' })).not.toBeInTheDocument()
  })

  it.each([
    ['driver', 'Khu vực tài xế'],
    ['accountant', 'Khu vực kế toán'],
  ])('shows the %s navigation scope', (role, label) => {
    render(
      <AppShell currentUser={{ ...currentUser, roles: [role] }}>
        <p>Nội dung</p>
      </AppShell>,
    )

    expect(screen.getByRole('link', { name: label })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
})
