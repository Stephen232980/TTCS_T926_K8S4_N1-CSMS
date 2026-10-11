import type { AuthenticatedUser, LoginInput } from '../model/auth'
import { AuthApiError, type AuthApi } from './authApi'

interface CurrentUserResponse {
  id: string
  email: string
  roles: string[]
  default_role?: string | null
}

interface ErrorResponse {
  detail?: unknown
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T

  let detail: unknown
  try {
    detail = ((await response.json()) as ErrorResponse).detail
  } catch {
    detail = undefined
  }
  throw new AuthApiError(response.status, detail)
}

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''

export class HttpAuthApi implements AuthApi {
  private readonly baseUrl: string

  constructor(baseUrl = configuredBaseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, '')
  }

  async setDefaultRole(role: string): Promise<AuthenticatedUser> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/default-role`, {
      method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    })
    const payload = await parseResponse<CurrentUserResponse>(response)
    return { id: payload.id, email: payload.email, roles: payload.roles, defaultRole: payload.default_role }
  }

  async login(input: LoginInput): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: input.email.trim(),
        password: input.password,
      }),
    })

    await parseResponse<{ status: 'authenticated' }>(response)
  }

  async logout(): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    })

    if (!response.ok) {
      let detail: unknown
      try {
        detail = ((await response.json()) as ErrorResponse).detail
      } catch {
        detail = undefined
      }
      throw new AuthApiError(response.status, detail)
    }
  }

  async getCurrentUser(signal?: AbortSignal): Promise<AuthenticatedUser> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/me`, {
      credentials: 'include',
      signal,
    })
    const payload = await parseResponse<CurrentUserResponse>(response)

    return {
      id: payload.id,
      email: payload.email,
      roles: payload.roles,
      ...(payload.default_role !== undefined ? { defaultRole: payload.default_role } : {}),
    }
  }
}
