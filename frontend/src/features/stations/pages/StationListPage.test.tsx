import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { StationApiError } from '../api/httpStationApi'
import { MockStationApi } from '../api/mockStationApi'
import type { StationApi } from '../api/stationApi'
import type { Station } from '../model/station'
import { StationListPage } from './StationListPage'

async function fillCreateForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Tên trạm'), 'Trạm Quận 7')
  await user.type(screen.getByLabelText('Địa chỉ'), '10 Nguyễn Thị Thập')
  await user.type(screen.getByLabelText('Vĩ độ'), '10.7356')
  await user.type(screen.getByLabelText('Kinh độ'), '106.7219')
}

describe('StationListPage create flow', () => {
  it('creates a station and refreshes the first page', async () => {
    const user = userEvent.setup()
    const onNotice = vi.fn()
    render(
      <StationListPage
        notice=""
        onNotice={onNotice}
        api={new MockStationApi([], 0)}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Tạo trạm' }))
    await fillCreateForm(user)
    await user.click(
      within(screen.getByRole('form', { name: 'Tạo trạm mới' })).getByRole(
        'button',
        { name: 'Tạo trạm' },
      ),
    )

    expect(await screen.findAllByText('Trạm Quận 7')).toHaveLength(2)
    expect(onNotice).toHaveBeenCalledWith('Đã tạo trạm Trạm Quận 7.')
    expect(
      screen.queryByRole('heading', { name: 'Tạo trạm mới' }),
    ).not.toBeInTheDocument()
  })

  it('prevents duplicate submissions while the request is pending', async () => {
    const user = userEvent.setup()
    const createStation = vi.fn(() => new Promise<Station>(() => undefined))
    const api: StationApi = {
      listStations: vi.fn().mockResolvedValue({
        items: [],
        page: 1,
        pageSize: 2,
        total: 0,
        totalPages: 0,
      }),
      createStation,
      updateStation: vi.fn(),
    }
    render(<StationListPage notice="" onNotice={() => undefined} api={api} />)

    await user.click(screen.getByRole('button', { name: 'Tạo trạm' }))
    await fillCreateForm(user)
    await user.dblClick(
      within(screen.getByRole('form', { name: 'Tạo trạm mới' })).getByRole(
        'button',
        { name: 'Tạo trạm' },
      ),
    )

    expect(createStation).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Đang lưu…' })).toBeDisabled()
  })

  it('keeps the form values visible when the API rejects the request', async () => {
    const user = userEvent.setup()
    const api = new MockStationApi([], 0)
    vi.spyOn(api, 'createStation').mockRejectedValue(
      new StationApiError(422, 'validation_error'),
    )
    render(<StationListPage notice="" onNotice={() => undefined} api={api} />)

    await user.click(screen.getByRole('button', { name: 'Tạo trạm' }))
    await fillCreateForm(user)
    await user.click(
      within(screen.getByRole('form', { name: 'Tạo trạm mới' })).getByRole(
        'button',
        { name: 'Tạo trạm' },
      ),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Dữ liệu chưa hợp lệ. Vui lòng kiểm tra lại các ô nhập.',
    )
    expect(screen.getByLabelText('Tên trạm')).toHaveValue('Trạm Quận 7')
    await waitFor(() => {
      expect(
        within(screen.getByRole('form', { name: 'Tạo trạm mới' })).getByRole(
          'button',
          { name: 'Tạo trạm' },
        ),
      ).toBeEnabled()
    })
  })
})

describe('StationListPage edit flow', () => {
  it('updates a station and reflects the response immediately in the list', async () => {
    const user = userEvent.setup()
    const onNotice = vi.fn()
    const api = new MockStationApi(
      [
        {
          id: 'station-1',
          name: 'Trạm ban đầu',
          address: 'Địa chỉ ban đầu',
          latitude: 10.7,
          longitude: 106.7,
          status: 'inactive',
          createdAt: '2026-09-29T10:00:00Z',
          updatedAt: '2026-09-29T10:00:00Z',
        },
      ],
      0,
    )
    render(<StationListPage notice="" onNotice={onNotice} api={api} />)

    const editButtons = await screen.findAllByRole('button', {
      name: 'Chỉnh sửa Trạm ban đầu',
    })
    await user.click(editButtons[0])
    const nameInput = screen.getByLabelText('Tên trạm')
    await user.clear(nameInput)
    await user.type(nameInput, 'Trạm đã sửa')
    await user.click(
      within(screen.getByRole('form', { name: 'Chỉnh sửa trạm' })).getByRole(
        'button',
        { name: 'Lưu thay đổi' },
      ),
    )

    expect(await screen.findAllByText('Trạm đã sửa')).toHaveLength(2)
    expect(screen.queryAllByText('Trạm ban đầu')).toHaveLength(0)
    expect(onNotice).toHaveBeenCalledWith('Đã cập nhật trạm Trạm đã sửa.')
    expect(
      screen.queryByRole('form', { name: 'Chỉnh sửa trạm' }),
    ).not.toBeInTheDocument()
  })
})
