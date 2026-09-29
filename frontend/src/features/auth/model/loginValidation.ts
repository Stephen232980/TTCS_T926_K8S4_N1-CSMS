import type { LoginInput } from './auth'

export interface LoginErrors {
  email?: string
  password?: string
}

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function validateLogin(input: LoginInput): LoginErrors {
  const errors: LoginErrors = {}
  const email = input.email.trim()

  if (!email) {
    errors.email = 'Vui lòng nhập email.'
  } else if (!emailPattern.test(email)) {
    errors.email = 'Email chưa đúng định dạng.'
  }

  if (!input.password) {
    errors.password = 'Vui lòng nhập mật khẩu.'
  } else if (input.password.length > 1024) {
    errors.password = 'Mật khẩu không được vượt quá 1024 ký tự.'
  }

  return errors
}
