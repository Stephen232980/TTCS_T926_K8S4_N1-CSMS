import { type FormEvent, useRef, useState } from 'react'
import { Icon } from '../../../components/icons/Icon'
import { AuthApiError, type AuthApi } from '../api/authApi'
import { HttpAuthApi } from '../api/httpAuthApi'
import type { LoginErrors } from '../model/loginValidation'
import { validateLogin } from '../model/loginValidation'

const defaultAuthApi = new HttpAuthApi()

function loginErrorMessage(error: unknown): string {
  if (error instanceof AuthApiError) {
    if (error.status === 401) return 'Email hoặc mật khẩu không đúng.'
    if (error.status === 423) {
      return 'Đăng nhập tạm thời bị khóa. Vui lòng thử lại sau 15 phút.'
    }
    if (error.status === 422) {
      return 'Email hoặc mật khẩu chưa hợp lệ. Vui lòng kiểm tra lại.'
    }
  }
  return 'Không thể đăng nhập. Vui lòng thử lại.'
}

interface LoginPageProps {
  api?: AuthApi
  onAuthenticated: () => void | Promise<void>
  sessionMessage?: string
}

export function LoginPage({
  api = defaultAuthApi,
  onAuthenticated,
  sessionMessage = '',
}: LoginPageProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<LoginErrors>({})
  const [submitError, setSubmitError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submitInFlight = useRef(false)
  const emailInputRef = useRef<HTMLInputElement>(null)
  const passwordInputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitInFlight.current) return

    const nextErrors = validateLogin({ email, password })
    setErrors(nextErrors)
    setSubmitError('')
    if (Object.keys(nextErrors).length > 0) {
      if (nextErrors.email) emailInputRef.current?.focus()
      else if (nextErrors.password) passwordInputRef.current?.focus()
      return
    }

    submitInFlight.current = true
    setIsSubmitting(true)
    try {
      await api.login({ email, password })
      await onAuthenticated()
    } catch (error: unknown) {
      setSubmitError(loginErrorMessage(error))
    } finally {
      submitInFlight.current = false
      setIsSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-intro" aria-labelledby="login-intro-title">
        <a className="login-brand" href="#login" aria-label="CSMS - Đăng nhập">
          <span className="brand__mark"><Icon name="bolt" /></span>
          <span>CSMS</span>
        </a>
        <div className="login-intro__content">
          <h1 id="login-intro-title">Vận hành hệ thống sạc trong một nhịp làm việc rõ ràng.</h1>
          <p>Theo dõi trạm, khai báo trụ và quản lý phần việc đúng theo vai trò của bạn.</p>
        </div>
        <p className="login-intro__note">Hệ thống quản lý trạm sạc</p>
      </section>

      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-panel__inner">
          <div className="login-panel__heading">
            <h2 id="login-title">Đăng nhập</h2>
            <p>Dùng tài khoản CSMS đã được cấp để tiếp tục.</p>
          </div>

          {sessionMessage && <div className="login-session-message" role="status">{sessionMessage}</div>}

          <form className="login-form" onSubmit={handleSubmit} noValidate>
            <div className="form-field">
              <label htmlFor="login-email">Email</label>
              <input
                id="login-email"
                ref={emailInputRef}
                type="email"
                autoComplete="email"
                value={email}
                disabled={isSubmitting}
                aria-invalid={Boolean(errors.email)}
                aria-describedby={errors.email ? 'login-email-error' : undefined}
                onChange={(event) => {
                  setEmail(event.target.value)
                  if (errors.email) setErrors((current) => ({ ...current, email: undefined }))
                }}
                placeholder="ten@congty.vn"
              />
              {errors.email && <span className="field-error" id="login-email-error">{errors.email}</span>}
            </div>

            <div className="form-field">
              <label htmlFor="login-password">Mật khẩu</label>
              <input
                id="login-password"
                ref={passwordInputRef}
                type="password"
                autoComplete="current-password"
                value={password}
                disabled={isSubmitting}
                aria-invalid={Boolean(errors.password)}
                aria-describedby={errors.password ? 'login-password-error' : undefined}
                onChange={(event) => {
                  setPassword(event.target.value)
                  if (errors.password) setErrors((current) => ({ ...current, password: undefined }))
                }}
              />
              {errors.password && <span className="field-error" id="login-password-error">{errors.password}</span>}
            </div>

            {submitError && <div className="login-submit-error" role="alert">{submitError}</div>}

            <button className="login-submit" type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Đang đăng nhập…' : 'Đăng nhập'}
            </button>
          </form>
        </div>
      </section>
    </main>
  )
}
