import type { AuthenticatedUser, LoginInput } from '../model/auth'

export interface AuthApi {
  setDefaultRole?(role: string): Promise<AuthenticatedUser>
  login(input: LoginInput): Promise<void>
  logout(): Promise<void>
  getCurrentUser(signal?: AbortSignal): Promise<AuthenticatedUser>
}

export class AuthApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail?: unknown) {
    super(`Auth API request failed with status ${status}`)
    this.name = 'AuthApiError'
    this.status = status
    this.detail = detail
  }
}
