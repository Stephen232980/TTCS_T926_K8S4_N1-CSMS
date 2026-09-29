import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ChargePointApiError, type ChargePointApi } from '../api/chargePointApi'
import type { ChargePoint } from '../model/chargePoint'
import {
  validateChargePointCode,
  validateConnectorCount,
} from '../model/chargePointValidation'

type AvailabilityState = 'idle' | 'checking' | 'available' | 'unavailable' | 'error'

function submitErrorMessage(error: unknown): string {
  if (error instanceof ChargePointApiError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
    if (error.status === 403) return 'Bạn không có quyền thêm trụ vào trạm này.'
    if (error.status === 404) return 'Trạm không còn tồn tại.'
    if (error.status === 422) return 'Dữ liệu chưa hợp lệ. Vui lòng kiểm tra lại.'
  }
  return 'Không thể thêm trụ sạc. Vui lòng thử lại.'
}

interface ChargePointFormProps {
  stationId: string
  api: ChargePointApi
  onCreated: (chargePoint: ChargePoint) => void
}

export function ChargePointForm({
  stationId,
  api,
  onCreated,
}: ChargePointFormProps) {
  const [code, setCode] = useState('')
  const [connectorCount, setConnectorCount] = useState('1')
  const [codeError, setCodeError] = useState('')
  const [connectorCountError, setConnectorCountError] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [availability, setAvailability] = useState<AvailabilityState>('idle')
  const [lastCheckedCode, setLastCheckedCode] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const availabilityController = useRef<AbortController | null>(null)
  const availabilityRequest = useRef(0)
  const submitInFlight = useRef(false)

  useEffect(
    () => () => availabilityController.current?.abort(),
    [],
  )

  const handleCodeChange = (value: string) => {
    availabilityController.current?.abort()
    availabilityRequest.current += 1
    setCode(value)
    setCodeError('')
    setAvailability('idle')
    setLastCheckedCode('')
    setSubmitError('')
  }

  const handleCodeBlur = async () => {
    const normalizedCode = code.trim()
    const validationError = validateChargePointCode(code)
    if (validationError) {
      setCodeError(validationError)
      setAvailability('idle')
      return
    }
    if (
      normalizedCode === lastCheckedCode &&
      (availability === 'available' || availability === 'unavailable')
    ) {
      return
    }

    availabilityController.current?.abort()
    const controller = new AbortController()
    availabilityController.current = controller
    const requestId = availabilityRequest.current + 1
    availabilityRequest.current = requestId
    setAvailability('checking')
    setCodeError('')

    try {
      const result = await api.checkCodeAvailability(normalizedCode, controller.signal)
      if (controller.signal.aborted || requestId !== availabilityRequest.current) return

      setLastCheckedCode(result.code)
      if (result.available) {
        setAvailability('available')
      } else {
        setAvailability('unavailable')
        setCodeError('Mã trụ đã được sử dụng.')
      }
    } catch (error: unknown) {
      if (controller.signal.aborted || requestId !== availabilityRequest.current) return
      setAvailability('error')
      if (error instanceof ChargePointApiError && error.status === 401) {
        setCodeError('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')
      } else {
        setCodeError('Không thể kiểm tra mã. Rời ô nhập để thử lại.')
      }
    }
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitInFlight.current) return

    const normalizedCode = code.trim()
    const nextCodeError = validateChargePointCode(code)
    const nextConnectorCountError = validateConnectorCount(connectorCount)
    setCodeError(nextCodeError)
    setConnectorCountError(nextConnectorCountError)
    setSubmitError('')

    if (nextCodeError || nextConnectorCountError) return
    if (availability !== 'available' || lastCheckedCode !== normalizedCode) {
      setCodeError('Rời ô nhập để kiểm tra mã trước khi lưu.')
      return
    }

    submitInFlight.current = true
    setIsSubmitting(true)

    try {
      const created = await api.createChargePoint(stationId, {
        code: normalizedCode,
        connectorCount: Number(connectorCount),
      })
      onCreated(created)
      setCode('')
      setConnectorCount('1')
      setCodeError('')
      setConnectorCountError('')
      setAvailability('idle')
      setLastCheckedCode('')
    } catch (error: unknown) {
      if (
        error instanceof ChargePointApiError &&
        error.status === 409 &&
        error.detail === 'charge_point_code_already_exists'
      ) {
        setAvailability('unavailable')
        setCodeError('Mã trụ đã được sử dụng.')
      } else {
        setSubmitError(submitErrorMessage(error))
      }
    } finally {
      submitInFlight.current = false
      setIsSubmitting(false)
    }
  }

  const availabilityMessage =
    availability === 'checking'
      ? 'Đang kiểm tra mã…'
      : availability === 'available'
        ? 'Mã trụ có thể sử dụng.'
        : ''

  return (
    <form className="charge-point-form" aria-label="Thêm trụ sạc" onSubmit={handleSubmit}>
      <div className="form-field">
        <label htmlFor="charge-point-code">Mã trụ</label>
        <input
          id="charge-point-code"
          name="code"
          value={code}
          maxLength={64}
          placeholder="Ví dụ: CP-Q1-001"
          autoComplete="off"
          aria-invalid={Boolean(codeError)}
          aria-describedby="charge-point-code-message"
          disabled={isSubmitting}
          onChange={(event) => handleCodeChange(event.target.value)}
          onBlur={handleCodeBlur}
        />
        <span
          id="charge-point-code-message"
          className={codeError ? 'field-error' : 'field-help'}
          role={codeError ? 'alert' : undefined}
        >
          {codeError || availabilityMessage || 'Mã phải duy nhất trong toàn hệ thống.'}
        </span>
      </div>

      <div className="form-field">
        <label htmlFor="connector-count">Số đầu nối</label>
        <input
          id="connector-count"
          name="connectorCount"
          type="number"
          min="1"
          max="4"
          step="1"
          value={connectorCount}
          aria-invalid={Boolean(connectorCountError)}
          aria-describedby="connector-count-message"
          disabled={isSubmitting}
          onChange={(event) => {
            setConnectorCount(event.target.value)
            setConnectorCountError('')
            setSubmitError('')
          }}
        />
        <span
          id="connector-count-message"
          className={connectorCountError ? 'field-error' : 'field-help'}
          role={connectorCountError ? 'alert' : undefined}
        >
          {connectorCountError || 'Chọn từ 1 đến 4 đầu nối.'}
        </span>
      </div>

      {submitError && <div className="form-submit-error" role="alert">{submitError}</div>}

      <div className="charge-point-form__actions">
        <button
          className="primary-button"
          type="submit"
          disabled={isSubmitting || availability === 'checking'}
        >
          {isSubmitting ? 'Đang thêm…' : 'Thêm trụ sạc'}
        </button>
      </div>
    </form>
  )
}
