import { describe, expect, it } from 'vitest'
import { validateLogin } from './loginValidation'

describe('validateLogin', () => {
  it('requires an email and password', () => {
    expect(validateLogin({ email: ' ', password: '' })).toEqual({
      email: 'Vui lòng nhập email.',
      password: 'Vui lòng nhập mật khẩu.',
    })
  })

  it('rejects an invalid email', () => {
    expect(validateLogin({ email: 'owner', password: 'secret' })).toEqual({
      email: 'Email chưa đúng định dạng.',
    })
  })

  it('accepts a valid login input', () => {
    expect(
      validateLogin({ email: 'owner@example.com', password: 'secret' }),
    ).toEqual({})
  })
})
