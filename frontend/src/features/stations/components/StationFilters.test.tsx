import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { StationFilters } from './StationFilters'

describe('StationFilters', () => {
  it('reports search text changes', async () => {
    const user = userEvent.setup()
    const onSearchChange = vi.fn()

    render(
      <StationFilters
        search=""
        status=""
        onSearchChange={onSearchChange}
        onStatusChange={() => undefined}
      />,
    )

    await user.type(screen.getByRole('searchbox', { name: 'Tìm trạm' }), 'Quận 1')

    expect(onSearchChange).toHaveBeenCalled()
    expect(onSearchChange).toHaveBeenLastCalledWith('1')
  })

  it('reports status changes', async () => {
    const user = userEvent.setup()
    const onStatusChange = vi.fn()

    render(
      <StationFilters
        search=""
        status=""
        onSearchChange={() => undefined}
        onStatusChange={onStatusChange}
      />,
    )

    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Trạng thái' }),
      'active',
    )

    expect(onStatusChange).toHaveBeenCalledWith('active')
  })
})
