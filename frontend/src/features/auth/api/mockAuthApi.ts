import type { AuthenticatedUser } from '../model/auth'
import { AuthApiError, type AuthApi } from './authApi'

const defaultUser: AuthenticatedUser = {
  id: 'a4e67f4a-1c6c-4dfa-a01d-581b624749af',
  email: 'owner@example.com',
  roles: ['station_owner'],
}

export class MockAuthApi implements AuthApi {
  private currentUser: AuthenticatedUser | null

  constructor(user: AuthenticatedUser | null = defaultUser) {
    this.currentUser = user
  }

  async login(): Promise<void> {
    this.currentUser = defaultUser
  }

  async getCurrentUser(): Promise<AuthenticatedUser> {
    if (this.currentUser === null) throw new AuthApiError(401)
    return this.currentUser
  }
}
