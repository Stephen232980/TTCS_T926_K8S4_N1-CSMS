
import { useRef, useState, type FormEvent } from 'react'

export interface TariffValues {
  pricePerKwh: number
  idleFeePerMinute: number
  graceMinutes: number
}

type Field = keyof TariffValues

const fields: { key: Field; label: string }[] = [
  { key: 'pricePerKwh', label: 'Đơn giá mỗi kWh (VNĐ)' },
  { key: 'idleFeePerMinute', label: 'Phí chiếm trụ mỗi phút (VNĐ)' },
  { key: 'graceMinutes', label: 'Thời gian ân hạn (phút)' },
]

function validateNumber(value: string): string {
  if (value.trim() === '') return 'Không được để trống.'
  if (!/^\d+$/.test(value.trim())) {
    return 'Chỉ được nhập số nguyên không âm.'
  }
  if (!Number.isSafeInteger(Number(value))) {
    return 'Giá trị vượt phạm vi cho phép.'
  }
  return ''
}

interface TariffFormProps {
  currentTariff: TariffValues | null
  onSave: (values: TariffValues) => Promise<void>
}

export function TariffForm({
  currentTariff,
  onSave,
}: TariffFormProps) {
  const [values, setValues] = useState({
    pricePerKwh: '',
    idleFeePerMinute: '',
    graceMinutes: '',
  })

  const [touched, setTouched] = useState<
    Partial<Record<Field, boolean>>
  >({})

  const [saving, setSaving] = useState(false)
  const sendingRef = useRef(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const hasError = fields.some(
    ({ key }) => validateNumber(values[key]) !== '',
  )

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (sendingRef.current || hasError) return

    sendingRef.current = true
    setSaving(true)
    setError('')
    setSuccess('')

    try {
      await onSave({
        pricePerKwh: Number(values.pricePerKwh),
        idleFeePerMinute: Number(values.idleFeePerMinute),
        graceMinutes: Number(values.graceMinutes),
      })

     setSuccess('Đã cập nhật biểu giá xem trước (chưa lưu vào hệ thống).')
    } catch {
      setError('Không thể lưu biểu giá. Vui lòng thử lại.')
    } finally {
      sendingRef.current = false
      setSaving(false)
    }
  }

  return (
    <section className="owner-panel">
      <h2>Biểu giá đang áp dụng</h2>

      {currentTariff ? (
        <div>
          <p>
            Đơn giá: {currentTariff.pricePerKwh.toLocaleString('vi-VN')} VNĐ/kWh
          </p>
          <p>
            Phí chiếm trụ: {currentTariff.idleFeePerMinute.toLocaleString('vi-VN')} VNĐ/phút
          </p>
          <p>
            Ân hạn: {currentTariff.graceMinutes} phút
          </p>
        </div>
      ) : (
        <p>Trạm chưa có biểu giá đang áp dụng.</p>
      )}

      <h2>Khai báo biểu giá</h2>

      <form onSubmit={handleSubmit} noValidate>
        {fields.map(({ key, label }) => {
          const fieldError = validateNumber(values[key])
          const showError = touched[key] && fieldError

          return (
            <label className="owner-field" key={key}>
              {label}

              <input
                type="text"
                inputMode="numeric"
                value={values[key]}
                disabled={saving}
                aria-invalid={Boolean(showError)}
                style={
                  showError
                    ? { borderColor: '#b91c1c' }
                    : undefined
                }
                onChange={(event) => {
                  setValues((previous) => ({
                    ...previous,
                    [key]: event.target.value,
                  }))
                  setTouched((previous) => ({
                    ...previous,
                    [key]: true,
                  }))
                  setSuccess('')
                }}
              />

              {showError && (
                <span role="alert" style={{ color: '#b91c1c' }}>
                  {fieldError}
                </span>
              )}
            </label>
          )
        })}

        {error && (
          <p className="owner-error" role="alert">
            {error}
          </p>
        )}

        {success && (
          <p className="owner-notice" role="status">
            {success}
          </p>
        )}

        <button
          type="submit"
          className="primary-button"
          disabled={saving || hasError}
        >
          {saving ? 'Đang lưu...' : 'Lưu biểu giá'}
        </button>
      </form>
    </section>
  )
}
