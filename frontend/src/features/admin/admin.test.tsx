import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from 'vitest'
import { AdminAccounts } from './AdminAccounts'
import { AdminAudit } from './AdminAudit'
import { AdminHealth } from './AdminHealth'
import { AdminWorkspace } from './AdminWorkspace'
import {
  adminRequest,
  AdminApiError,
  healthSegments,
  vietnamInstant,
  type Account,
  type HealthMetrics,
} from './adminApi'
import { SESSION_UNAUTHORIZED_EVENT } from '../auth/sessionEvents'

const currentUser = {
  id: 'admin-id',
  email: 'admin@example.com',
  roles: ['admin'],
}
const account: Account = {
  id: 'member-id',
  email: 'member@example.com',
  roles: ['driver'],
  status: 'active',
  created_at: '2026-10-05T02:00:00Z',
  updated_at: '2026-10-05T02:00:00Z',
}
const roles = [
  { code: 'admin', name: 'Quản trị' },
  { code: 'driver', name: 'Tài xế' },
  { code: 'station_owner', name: 'Chủ trạm' },
]
const metrics: HealthMetrics = {
  online_charge_points: 2,
  registered_charge_points: 4,
  running_sessions: 1,
  error_messages_5m: null,
  error_messages_observed_5m: 1,
  response_latency_ms: null,
  response_count_5m: 0,
  window_complete: false,
}
const history = {
  from_at: '2026-10-04T03:00:00Z',
  to_at: '2026-10-05T03:00:00Z',
  available_since: '2026-10-05T03:00:00Z',
  resolution_seconds: 3600,
  aggregation: 'latest_observation',
  points: [
    {
      bucket_start: '2026-10-05T03:00:00Z',
      measured_at: '2026-10-05T03:00:00Z',
      metrics,
    },
  ],
}
const health = {
  generated_at: '2026-10-05T03:00:00Z',
  refresh_after_seconds: 30,
  stale_after_seconds: 90,
  status: 'current',
  snapshot: {
    collected_at: '2026-10-05T03:00:00Z',
    window_start: '2026-10-05T02:55:00Z',
    window_end: '2026-10-05T03:00:00Z',
    metrics,
  },
}
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
let fetcher: Mock<(url: string, options?: RequestInit) => Promise<Response>>
beforeEach(() => {
  localStorage.clear()
  window.location.hash = ''
  fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/admin/roles')) return response(roles)
    if (url.includes('/admin/accounts?'))
      return response({ items: [account], page: 1, total: 1, total_pages: 1 })
    if (url.endsWith('/admin/accounts/member-id'))
      return response(
        options?.method === 'PATCH'
          ? {
              ...account,
              ...JSON.parse(String(options.body)),
              updated_at: '2026-10-05T03:00:00Z',
            }
          : account,
      )
    if (url.includes('/system-health/history')) return response(history)
    if (url.endsWith('/system-health')) return response(health)
    if (url.includes('/control-audit'))
      return response({
        items: [
          {
            id: 'audit-id',
            actor: currentUser.email,
            charge_point_code: 'CP-01',
            transaction_id: 1,
            action: 'Reset',
            status: 'Accepted',
            payload: { type: 'Soft' },
            created_at: account.created_at,
            received_at: account.created_at,
          },
        ],
        page: 1,
        total: 1,
        total_pages: 1,
      })
    if (url.includes('/account-audit'))
      return response({ items: [], page: 1, total: 0, total_pages: 1 })
    if (url.endsWith('/admin/accounts') && options?.method === 'POST')
      return response({ ...account, ...JSON.parse(String(options.body)) }, 201)
    return response({ detail: 'Not found' }, 404)
  })
  vi.stubGlobal('fetch', fetcher)
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.location.hash = ''
})

describe('admin account workflows', () => {
  it('creates through all three steps with selected roles and never persists the password', async () => {
    const user = userEvent.setup()
    render(<AdminAccounts currentUser={currentUser} />)
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Cấp tài khoản' }),
      ).toBeEnabled(),
    )
    await user.click(screen.getByRole('button', { name: 'Cấp tài khoản' }))
    await user.type(
      screen.getByLabelText('Email thành viên'),
      'new@example.com',
    )
    await user.type(
      screen.getByLabelText('Mật khẩu ban đầu'),
      'Local-member-2026!',
    )
    await user.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    await user.click(screen.getByLabelText('Tài xế'))
    await user.click(screen.getByLabelText('Chủ trạm'))
    await user.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    expect(
      screen.queryByDisplayValue('Local-member-2026!'),
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Quay lại' }))
    expect(screen.getByLabelText('Tài xế')).toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    await user.click(screen.getByRole('button', { name: 'Cấp tài khoản' }))
    await screen.findByText(/Đã cấp tài khoản/)
    const call = fetcher.mock.calls.find(
      ([, options]) => options?.method === 'POST',
    )!
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      email: 'new@example.com',
      password: 'Local-member-2026!',
      roles: ['driver', 'station_owner'],
    })
    expect(JSON.stringify(localStorage)).not.toContain('Local-member-2026!')
  })
  it('requires confirmation and sends the latest version when locking', async () => {
    const user = userEvent.setup()
    render(<AdminAccounts currentUser={currentUser} />)
    await user.click(
      await screen.findByRole('button', { name: /member@example.com/ }),
    )
    await user.click(
      await screen.findByRole('button', { name: 'Khóa tài khoản' }),
    )
    expect(
      fetcher.mock.calls.some(([, options]) => options?.method === 'PATCH'),
    ).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Xác nhận' }))
    await screen.findByText('Đã lưu thay đổi tài khoản.')
    const call = fetcher.mock.calls.find(
      ([, options]) => options?.method === 'PATCH',
    )!
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      expected_updated_at: account.updated_at,
      status: 'suspended',
    })
    expect(
      await screen.findByRole('button', { name: 'Mở khóa tài khoản' }),
    ).toBeInTheDocument()
  })
  it('reloads after a conflict and requires the user to review again', async () => {
    const user = userEvent.setup()
    const original = fetcher.getMockImplementation()!
    fetcher.mockImplementation(async (url: string, options?: RequestInit) =>
      options?.method === 'PATCH'
        ? response(
            {
              error: {
                code: 'stale_account',
                message: 'Tài khoản đã thay đổi. Hãy tải lại.',
              },
            },
            409,
          )
        : original(url, options),
    )
    render(<AdminAccounts currentUser={currentUser} />)
    await user.click(
      await screen.findByRole('button', { name: /member@example.com/ }),
    )
    await user.click(await screen.findByRole('button', { name: 'Sửa vai trò' }))
    await user.click(screen.getByLabelText('Chủ trạm'))
    await user.click(screen.getByRole('button', { name: 'Lưu vai trò' }))
    await screen.findByRole('alert')
    expect(
      await screen.findByRole('button', { name: 'Sửa vai trò' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Lưu vai trò' }),
    ).not.toBeInTheDocument()
  })
  it('does not offer lifecycle actions for inactive or own accounts', async () => {
    const original = fetcher.getMockImplementation()!
    fetcher.mockImplementation(async (url: string, options?: RequestInit) =>
      url.endsWith('/admin/accounts/member-id')
        ? response({ ...account, status: 'pending_deletion' })
        : original(url, options),
    )
    const user = userEvent.setup()
    render(<AdminAccounts currentUser={currentUser} />)
    await user.click(
      await screen.findByRole('button', { name: /member@example.com/ }),
    )
    await screen.findByText('Trạng thái này chỉ cho phép xem thông tin.')
    expect(
      screen.queryByRole('button', { name: 'Sửa vai trò' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Khóa tài khoản' }),
    ).not.toBeInTheDocument()
  })
  it('keeps the first-use guide collapsed across visits', async () => {
    const user = userEvent.setup()
    const view = render(<AdminAccounts currentUser={currentUser} />)
    const guide = screen.getByText('Bắt đầu trong 3 bước').closest('details')!
    await user.click(within(guide).getByText('Bắt đầu trong 3 bước'))
    await waitFor(() =>
      expect(localStorage.getItem('csms-admin-guide-open')).toBe('false'),
    )
    view.unmount()
    render(<AdminAccounts currentUser={currentUser} />)
    expect(
      screen.getByText('Bắt đầu trong 3 bước').closest('details'),
    ).not.toHaveAttribute('open')
  })
})
describe('journal and real health contracts', () => {
  it('explains Accepted and renders the actual command payload read-only', async () => {
    const user = userEvent.setup()
    render(<AdminAudit />)
    await user.click(
      await screen.findByRole('button', { name: /Khởi động lại trụ/ }),
    )
    expect(
      screen.getByText(/chưa xác nhận hành động vật lý/),
    ).toBeInTheDocument()
    await user.click(screen.getByText('Nội dung lệnh'))
    expect(screen.getByText(/"Soft"/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Sửa' }),
    ).not.toBeInTheDocument()
  })
  it('applies exact filters in Vietnam time and clears them when switching sources', async () => {
    const user = userEvent.setup()
    render(<AdminAudit />)
    await screen.findByRole('button', { name: /Khởi động lại trụ/ })
    await user.type(screen.getByLabelText('Trụ'), 'CP-01')
    fireEvent.change(screen.getByLabelText('Từ (giờ Việt Nam)'), {
      target: { value: '2026-10-05T10:00' },
    })
    await user.click(screen.getByRole('button', { name: 'Áp dụng' }))
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url]) =>
            url.includes('from_at=2026-10-05T03%3A00%3A00.000Z') &&
            url.includes('charge_point_code=CP-01'),
        ),
      ).toBe(true),
    )
    await user.click(screen.getByRole('button', { name: 'Tài khoản' }))
    await screen.findByText('Chưa có thao tác phù hợp với bộ lọc này.')
    const url = fetcher.mock.calls.find(([u]) =>
      u.includes('/account-audit'),
    )![0]
    expect(url).not.toContain('charge_point_code')
    expect(url).not.toContain('from_at')
  })
  it('never connects a chart across null gaps and retains real zero', () => {
    const point = history.points[0]
    const segments = healthSegments(
      [
        point,
        { ...point, metrics: null },
        { ...point, metrics: { ...metrics, online_charge_points: 0 } },
      ],
      'online_charge_points',
    )
    expect(segments.map((s) => s.map((p) => p.value))).toEqual([[2], [0]])
    expect(vietnamInstant('2026-10-05T10:00')).toBe('2026-10-05T03:00:00.000Z')
  })
  it('shows warm-up and absent latency, supports expansion and pause without extra fetch', async () => {
    const user = userEvent.setup()
    render(<AdminHealth />)
    await screen.findByText(/Chưa đủ cửa sổ 5 phút/)
    expect(screen.getAllByRole('img')).toHaveLength(4)
    expect(screen.getAllByText('—')).toHaveLength(2)
    await user.click(
      screen.getByRole('button', { name: 'Phóng to Trụ trực tuyến' }),
    )
    expect(screen.getAllByRole('img')).toHaveLength(1)
    await user.click(
      screen.getByRole('button', { name: 'Thu gọn Trụ trực tuyến' }),
    )
    expect(screen.getAllByRole('img')).toHaveLength(4)
    const calls = fetcher.mock.calls.length
    await user.click(screen.getByRole('button', { name: 'Tạm dừng cập nhật' }))
    expect(fetcher.mock.calls).toHaveLength(calls)
    await user.click(screen.getByRole('button', { name: 'Cập nhật ngay' }))
    await waitFor(() => expect(fetcher.mock.calls.length).toBe(calls + 2))
  })
  it('preserves last measurements after refresh failure without pretending success', async () => {
    const user = userEvent.setup()
    render(<AdminHealth />)
    await screen.findByText(/Chưa đủ cửa sổ 5 phút/)
    fetcher.mockImplementation(async () =>
      response({ error: { message: 'Không đọc được DB' } }, 503),
    )
    await user.click(screen.getByRole('button', { name: 'Cập nhật ngay' }))
    await screen.findByRole('alert')
    expect(screen.getByText('Không đọc được DB')).toBeInTheDocument()
    expect(screen.getAllByRole('img')).toHaveLength(4)
    expect(screen.getByText(/Đo lúc/)).toHaveTextContent('10:00:00')
  })
  it('does not fetch administrative data for a user without admin', () => {
    render(
      <AdminWorkspace
        currentUser={{ ...currentUser, roles: ['station_owner'] }}
        onLogout={vi.fn()}
      />,
    )
    expect(
      screen.getByText('Bạn không có quyền truy cập quản trị.'),
    ).toBeInTheDocument()
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('uses the structured API error and broadcasts expired sessions', async () => {
    const unauthorized = vi.fn()
    window.addEventListener(SESSION_UNAUTHORIZED_EVENT, unauthorized)
    fetcher.mockResolvedValue(
      response(
        { error: { code: 'unauthorized', message: 'Hết phiên', fields: [] } },
        401,
      ),
    )
    await expect(adminRequest('/admin/roles')).rejects.toBeInstanceOf(
      AdminApiError,
    )
    expect(unauthorized).toHaveBeenCalledOnce()
    window.removeEventListener(SESSION_UNAUTHORIZED_EVENT, unauthorized)
  })
})
