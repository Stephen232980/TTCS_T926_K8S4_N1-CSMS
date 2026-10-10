import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { TariffHistoryPanel } from './TariffHistoryPanel'
import type { TariffVersion } from './tariffApi'

afterEach(() => vi.unstubAllGlobals())
const today = '2026-10-10'
const version = (
  id: string,
  date: string,
  editable: boolean,
): TariffVersion => ({
  id,
  effective_from: date,
  editable,
  status: editable ? 'upcoming' : 'current',
  created_at: today + 'T00:00:00Z',
  idle_rate_vnd_per_minute: '500',
  grace_minutes: 5,
  bands: [
    {
      start_min: 0,
      end_min: 1440,
      energy_rate_vnd_per_kwh: '9223372036854775807',
      label: 'Cả ngày',
    },
  ],
})
const current = version('current', today, false)
const future = version('future', '2026-10-11', true)
function mockApi(
  options: { reject?: string; historyFailure?: boolean; total?: number } = {},
) {
  let items = [future, current]
  let failure = options.historyFailure
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'PATCH') {
      if (options.reject)
        return new Response(JSON.stringify({ detail: options.reject }), {
          status: 409,
        })
      const body = JSON.parse(init.body as string)
      items = [
        {
          ...future,
          effective_from: body.effective_from,
          bands: [{ ...future.bands[0], energy_rate_vnd_per_kwh: '4000' }],
        },
        current,
      ]
      return new Response(JSON.stringify(items[0]))
    }
    if (init?.method === 'POST') {
      items = [version('new', '2026-10-12', true), ...items]
      return new Response(JSON.stringify({ id: 'new' }), { status: 201 })
    }
    if (url.includes('/context'))
      return new Response(
        JSON.stringify({
          today,
          timezone: 'Asia/Ho_Chi_Minh',
          has_versions: true,
          current,
          upcoming: items[0],
        }),
      )
    if (failure) {
      failure = false
      return new Response('{}', { status: 503 })
    }
    return new Response(
      JSON.stringify({
        today,
        timezone: 'Asia/Ho_Chi_Minh',
        items,
        page: url.includes('page=2') ? 2 : 1,
        page_size: 20,
        total: options.total ?? items.length,
      }),
    )
  })
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}

it('shows two versions, locks effective versions and reuses the creation form', async () => {
  mockApi()
  render(<TariffHistoryPanel stationId="station" />)
  expect(await screen.findByText('Đang áp dụng')).toBeInTheDocument()
  expect(screen.getByText('Sắp hiệu lực')).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: `Sửa biểu giá ${today}` }),
  ).not.toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: 'Sửa biểu giá 2026-10-11' }),
  ).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: /Xoá phiên bản/ }),
  ).not.toBeInTheDocument()
  expect(
    await screen.findByRole('button', { name: 'Lưu biểu giá' }),
  ).toBeInTheDocument()
})

it('prefills and edits future bands, preserves labels and exact BIGINT, then reloads history', async () => {
  const fetcher = mockApi()
  render(<TariffHistoryPanel stationId="station" />)
  fireEvent.click(
    await screen.findByRole('button', { name: 'Sửa biểu giá 2026-10-11' }),
  )
  expect(
    screen.queryByRole('button', { name: 'Lưu biểu giá' }),
  ).not.toBeInTheDocument()
  expect(screen.getByLabelText('Đơn giá khung 1')).toHaveValue(
    '9223372036854775807',
  )
  fireEvent.change(screen.getByLabelText('Ngày hiệu lực'), {
    target: { value: '2026-10-12' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))
  await screen.findByRole('button', { name: 'Sửa biểu giá 2026-10-12' })
  const call = fetcher.mock.calls.find(([, init]) => init?.method === 'PATCH')!
  expect(call[0]).toContain('/tariffs/future')
  expect(call[1]?.body).toContain(
    '"energy_rate_vnd_per_kwh":9223372036854775807',
  )
  expect(call[1]?.body).toContain('"label":"Cả ngày"')
  expect(
    fetcher.mock.calls.filter(([, init]) => init?.method === 'POST'),
  ).toHaveLength(0)
  expect(
    await screen.findByRole('button', { name: 'Lưu biểu giá' }),
  ).toBeInTheDocument()
})

it('blocks an edit when the server reports the version became immutable', async () => {
  const fetcher = mockApi({ reject: 'tariff_immutable' })
  render(<TariffHistoryPanel stationId="station" />)
  fireEvent.click(
    await screen.findByRole('button', { name: 'Sửa biểu giá 2026-10-11' }),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))
  expect(
    await screen.findByText(
      /Phiên bản đã hiệu lực hoặc đã dùng, không thể sửa/,
    ),
  ).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Lưu thay đổi' }),
  ).not.toBeInTheDocument()
  expect(
    fetcher.mock.calls.filter(([, init]) => init?.method === 'PATCH'),
  ).toHaveLength(1)
})

it('keeps the edit form and values on a duplicate-date rejection', async () => {
  mockApi({ reject: 'tariff_duplicate_date' })
  render(<TariffHistoryPanel stationId="station" />)
  fireEvent.click(
    await screen.findByRole('button', { name: 'Sửa biểu giá 2026-10-11' }),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))
  await waitFor(() =>
    expect(screen.getByLabelText(/^Ngày hiệu lực/)).toHaveAttribute(
      'aria-invalid',
      'true',
    ),
  )
  expect(screen.getByLabelText('Đơn giá khung 1')).toHaveValue(
    '9223372036854775807',
  )
  expect(
    screen.getByRole('button', { name: 'Lưu thay đổi' }),
  ).toBeInTheDocument()
})

it('cancels without writes and can retry a failed history read', async () => {
  const fetcher = mockApi({ historyFailure: true })
  render(<TariffHistoryPanel stationId="station" />)
  fireEvent.click(
    await screen.findByRole('button', { name: 'Tải lại lịch sử' }),
  )
  fireEvent.click(
    await screen.findByRole('button', { name: 'Sửa biểu giá 2026-10-11' }),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Huỷ sửa phiên bản' }))
  expect(
    await screen.findByRole('button', { name: 'Lưu biểu giá' }),
  ).toBeInTheDocument()
  expect(
    fetcher.mock.calls.filter(([, init]) => init?.method === 'PATCH'),
  ).toHaveLength(0)
})

it('refreshes history after creating a future version', async () => {
  const fetcher = mockApi()
  render(<TariffHistoryPanel stationId="station" />)
  await screen.findByRole('button', { name: 'Lưu biểu giá' })
  fireEvent.change(screen.getByLabelText('Ngày hiệu lực'), {
    target: { value: '2026-10-12' },
  })
  fireEvent.change(screen.getByLabelText('Đơn giá mỗi kWh (VNĐ)'), {
    target: { value: '3000' },
  })
  fireEvent.change(screen.getByLabelText('Phí chiếm trụ mỗi phút (VNĐ)'), {
    target: { value: '500' },
  })
  fireEvent.change(screen.getByLabelText('Thời gian ân hạn (phút)'), {
    target: { value: '5' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Lưu biểu giá' }))
  expect(
    await screen.findByRole('button', { name: 'Sửa biểu giá 2026-10-12' }),
  ).toBeInTheDocument()
  expect(
    fetcher.mock.calls.filter(([, init]) => init?.method === 'POST'),
  ).toHaveLength(1)
})
