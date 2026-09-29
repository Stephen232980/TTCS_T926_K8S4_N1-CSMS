export interface AuthenticatedUser {
  id: string
  email: string
  roles: string[]
}

export interface LoginInput {
  email: string
  password: string
}
