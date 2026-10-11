export interface AuthenticatedUser {
  id: string
  email: string
  roles: string[]
  defaultRole?: string | null
}

export interface LoginInput {
  email: string
  password: string
}
