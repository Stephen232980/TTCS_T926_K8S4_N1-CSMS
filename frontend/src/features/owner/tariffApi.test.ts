
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createStationTariff } from './tariffApi'

const validInput = {
  effectiveFrom: '2026-10-10',
  pricePerKwh: '3500',
  idleFeePerMinute: '500',
  graceMinutes: '5',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('T-62 - Tích hợp API lưu biểu giá', () => {
  it('gửi đúng station ID, payload và cookie đăng nhập', async () => {
    const fetchMock = vi.fn(async (url: string, options: RequestInit) => {
  void url
  void options

  return {
    ok: true,
    status: 201,
    json: async () => ({
      id: 'tariff-123',
      station_id: 'station-123',
      effective_from: '2026-10-10',
      created_at: '2026-10-10T00:00:00Z',
    }),
  }
})

    vi.stubGlobal('fetch', fetchMock)

    await createStationTariff('station-123', validInput)

    expect(fetchMock).toHaveBeenCalledTimes(1)

    const [url, options] = fetchMock.mock.calls[0]

    expect(url).toContain(
      '/api/v1/owner/stations/station-123/tariffs',
    )
    expect(options.method).toBe('POST')
    expect(options.credentials).toBe('include')

    expect(JSON.parse(String(options.body))).toEqual({
      effective_from: '2026-10-10',
      energy_rate_vnd_per_kwh: 3500,
      idle_rate_vnd_per_minute: 500,
      grace_minutes: 5,
    })
  })

  it('giữ chính xác số tiền 64-bit khi tạo JSON', async () => {
    const fetchMock = vi.fn(async (url: string, options: RequestInit) => {
  void url
  void options

  return {
    ok: true,
    status: 201,
    json: async () => ({
      id: 'tariff-123',
      station_id: 'station-123',
      effective_from: '2026-10-10',
      created_at: '2026-10-10T00:00:00Z',
    }),
  }
})

    vi.stubGlobal('fetch', fetchMock)

    await createStationTariff('station-123', {
      ...validInput,
      pricePerKwh: '9223372036854775807',
      graceMinutes: '2147483647',
    })

    const [, options] = fetchMock.mock.calls[0]
    const body = String(options.body)

    expect(body).toContain(
      '"energy_rate_vnd_per_kwh":9223372036854775807',
    )
    expect(body).toContain('"grace_minutes":2147483647')
  })

  it('chặn giá trị ân hạn vượt giới hạn', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      createStationTariff('station-123', {
        ...validInput,
        graceMinutes: '2147483648',
      }),
    ).rejects.toThrow('vượt giới hạn')

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('truyền lỗi validation 422 từ backend về frontend', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 422,
      json: async () => ({
        detail: [
          {
            loc: ['body', 'grace_minutes'],
            msg: 'Giá trị không hợp lệ',
            type: 'value_error',
          },
        ],
      }),
    }))

    vi.stubGlobal('fetch', fetchMock)

    await expect(
      createStationTariff('station-123', validInput),
    ).rejects.toMatchObject({
      status: 422,
      detail: [
        {
          loc: ['body', 'grace_minutes'],
          msg: 'Giá trị không hợp lệ',
        },
      ],
    })
  })
})
