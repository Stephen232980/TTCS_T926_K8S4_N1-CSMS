import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { WorkspaceChooser } from './WorkspaceChooser'
import { getHomeRole, getPermissions } from '../model/permissions'

const member = { id: 'member', email: 'member@example.com', roles: ['admin', 'station_owner'] }
describe('explicit landing preference', () => {
  it('has no role priority and admin has no operational actions', () => {
    expect(getHomeRole(member)).toBe('')
    expect(getHomeRole({ ...member, defaultRole: 'admin' })).toBe('admin')
    expect(getHomeRole({ ...member, defaultRole: 'operator' })).toBe('')
    expect(getPermissions({ ...member, roles: ['admin'] }).canControlChargers).toBe(false)
    expect(getPermissions({ ...member, roles: ['admin'] }).canCloseChargingSessions).toBe(false)
  })
  it('saves the preference through the backend before opening a workspace', async () => {
    const api = { login: vi.fn(), logout: vi.fn(), getCurrentUser: vi.fn(), setDefaultRole: vi.fn().mockResolvedValue({ ...member, defaultRole: 'admin' }) }
    const choose = vi.fn()
    render(<WorkspaceChooser user={member} api={api} onChoose={choose} onLogout={api.logout} />)
    await userEvent.click(screen.getByRole('button', { name: /Quản trị/ }))
    expect(api.setDefaultRole).toHaveBeenCalledWith('admin')
    expect(choose).toHaveBeenCalledWith('admin', { ...member, defaultRole: 'admin' })
  })
  it('keeps the user on the chooser when saving fails', async () => {
    const api = { login: vi.fn(), logout: vi.fn(), getCurrentUser: vi.fn(), setDefaultRole: vi.fn().mockRejectedValue(new Error('Không lưu được')) }
    const choose = vi.fn()
    render(<WorkspaceChooser user={member} api={api} onChoose={choose} onLogout={api.logout} />)
    await userEvent.click(screen.getByRole('button', { name: /Quản trị/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Không lưu được')
    expect(choose).not.toHaveBeenCalled()
  })
})
