import { beforeEach, describe, expect, it, vi } from 'vitest'
import { HttpAuthApi } from './httpAuthApi'

describe('HttpAuthApi', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('logs in with credentials and a trimmed email', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'authenticated' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const api = new HttpAuthApi('http://localhost:8001/')

    await api.login({
      email: ' owner@example.com ',
      password: 'mat-khau-dung',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/v1/auth/login',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({
          email: 'owner@example.com',
          password: 'mat-khau-dung',
        }),
      }),
    )
  })

  it('loads the current user with the session cookie', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 'a4e67f4a-1c6c-4dfa-a01d-581b624749af',
          email: 'owner@example.com',
          roles: ['station_owner'],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const controller = new AbortController()
    const api = new HttpAuthApi()

    await expect(api.getCurrentUser(controller.signal)).resolves.toEqual({
      id: 'a4e67f4a-1c6c-4dfa-a01d-581b624749af',
      email: 'owner@example.com',
      roles: ['station_owner'],
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/me', {
      credentials: 'include',
      signal: controller.signal,
    })
  })

  it('logs out with cookie credentials', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 }),
    )

    await new HttpAuthApi('http://localhost:8001/').logout()

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/v1/auth/logout',
      { method: 'POST', credentials: 'include' },
    )
  })

  it('preserves the current session when logout fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'service_unavailable' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(new HttpAuthApi().logout()).rejects.toMatchObject({
      status: 503,
      detail: 'service_unavailable',
    })
  })

  it('preserves the backend status and detail for login errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Email hoặc mật khẩu không đúng' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(
      new HttpAuthApi().login({
        email: 'owner@example.com',
        password: 'sai',
      }),
    ).rejects.toMatchObject({
      status: 401,
      detail: 'Email hoặc mật khẩu không đúng',
    })
  })
})
