import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import App from './App'
import { MockStationApi } from './features/stations/api/mockStationApi'

describe('App', () => {
  it('loads and filters an injected station API', async () => {
    const user = userEvent.setup()
    render(<App stationApi={new MockStationApi()} />)

    expect(screen.getByRole('heading', { name: 'Trạm sạc' })).toBeInTheDocument()
    expect(await screen.findAllByText('Trạm Quận 1')).toHaveLength(2)

    await user.type(screen.getByRole('searchbox', { name: 'Tìm trạm' }), 'Thủ Đức')

    expect(await screen.findAllByText('Trạm Thủ Đức')).toHaveLength(2)
    expect(screen.queryAllByText('Trạm Quận 1')).toHaveLength(0)
  })

  it('opens a station detail page and returns to the list', async () => {
    const user = userEvent.setup()
    render(<App stationApi={new MockStationApi(undefined, 0)} />)

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
})
