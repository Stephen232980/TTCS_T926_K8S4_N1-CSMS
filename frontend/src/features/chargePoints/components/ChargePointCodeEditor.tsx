import { useRef, useState, type FormEvent } from 'react'
import { ChargePointApiError, type ChargePointApi } from '../api/chargePointApi'
import type { ChargePoint } from '../model/chargePoint'
import { validateChargePointCode } from '../model/chargePointValidation'

interface ChargePointCodeEditorProps {
  chargePoint: ChargePoint
  api: ChargePointApi
  onUpdated: (chargePoint: ChargePoint) => void
  onCancel: () => void
}

function updateErrorMessage(error: unknown): string {
  if (error instanceof ChargePointApiError) {
    if (error.status === 403) return 'Bạn không có quyền sửa mã trụ này.'
    if (error.status === 404) return 'Không tìm thấy trụ sạc hoặc trụ đã bị xóa.'
    if (
      error.status === 409 &&
      error.detail === 'charge_point_code_locked_after_charging'
    ) {
      return 'Mã trụ đã được khóa sau phiên sạc đầu tiên và không thể thay đổi.'
    }
    if (
      error.status === 409 &&
      error.detail === 'charge_point_code_already_exists'
    ) {
      return 'Mã trụ đã được sử dụng. Hãy chọn mã khác.'
    }
    if (error.status === 422) return 'Mã trụ chưa hợp lệ. Hãy kiểm tra lại.'
  }
  return 'Không thể cập nhật mã trụ. Vui lòng thử lại.'
}

export function ChargePointCodeEditor({
  chargePoint,
  api,
  onUpdated,
  onCancel,
}: ChargePointCodeEditorProps) {
  const [code, setCode] = useState(chargePoint.code)
  const [codeError, setCodeError] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submitInFlight = useRef(false)
  const isLocked = chargePoint.codeLockedAt != null

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isLocked || submitInFlight.current) return

    const validationError = validateChargePointCode(code)
    setCodeError(validationError)
    setSubmitError('')
    if (validationError) return

    submitInFlight.current = true
    setIsSubmitting(true)
    try {
      const updated = await api.updateChargePoint(chargePoint.id, {
        code: code.trim(),
      })
      onUpdated(updated)
    } catch (error: unknown) {
      setSubmitError(updateErrorMessage(error))
    } finally {
      submitInFlight.current = false
      setIsSubmitting(false)
    }
  }

  return (
    <form
      className="charge-point-code-editor"
      aria-label={`Sửa mã trụ ${chargePoint.code}`}
      onSubmit={handleSubmit}
    >
      <div className="form-field">
        <label htmlFor={`charge-point-code-${chargePoint.id}`}>Mã trụ</label>
        <input
          id={`charge-point-code-${chargePoint.id}`}
          value={code}
          maxLength={64}
          autoComplete="off"
          disabled={isLocked || isSubmitting}
          aria-invalid={Boolean(codeError)}
          aria-describedby={`charge-point-code-help-${chargePoint.id}`}
          onChange={(event) => {
            setCode(event.target.value)
            setCodeError('')
            setSubmitError('')
          }}
        />
        <span
          id={`charge-point-code-help-${chargePoint.id}`}
          className={codeError ? 'field-error' : 'field-help'}
          role={codeError ? 'alert' : undefined}
        >
          {codeError ||
            (isLocked
              ? 'Mã đã khóa sau phiên sạc đầu tiên.'
              : 'Có thể sửa cho đến khi phiên sạc đầu tiên bắt đầu.')}
        </span>
      </div>

      {submitError && (
        <div className="form-submit-error" role="alert">
          {submitError}
        </div>
      )}

      <div className="charge-point-code-editor__actions">
        <button
          className="secondary-button"
          type="button"
          disabled={isSubmitting}
          onClick={onCancel}
        >
          Hủy
        </button>
        <button
          className="primary-button"
          type="submit"
          disabled={isLocked || isSubmitting || code.trim() === chargePoint.code}
        >
          {isSubmitting ? 'Đang lưu…' : 'Lưu mã trụ'}
        </button>
      </div>
    </form>
  )
}
