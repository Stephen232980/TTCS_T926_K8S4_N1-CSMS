import type { AuthenticatedUser, LoginInput } from '../model/auth'
import { AuthApiError, type AuthApi } from './authApi'

interface CurrentUserResponse {
  id: string
  email: string
  roles: string[]
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
    }
  }
}
