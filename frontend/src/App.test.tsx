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
})
