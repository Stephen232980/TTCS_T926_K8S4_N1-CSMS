import { StationMap } from '../../../components/maps/StationMap'
import { useRef, useState, type FormEvent } from 'react'
import type { Station, StationInput } from '../model/station'
import {
  validateStationForm,
  type StationFormErrors,
  type StationFormField,
  type StationFormValues,
} from '../model/stationValidation'

interface StationFormProps {
  mode: 'create' | 'edit'
  station?: Station
  isSubmitting?: boolean
  submitError?: string
  onSubmit: (input: StationInput) => void
  onCancel: () => void
}

function initialValues(station?: Station): StationFormValues {
  return {
    name: station?.name ?? '',
    address: station?.address ?? '',
    latitude: station ? String(station.latitude) : '',
    longitude: station ? String(station.longitude) : '',
  }
}

export function StationForm({
  mode,
  station,
  isSubmitting = false,
  submitError = '',
  onSubmit,
  onCancel,
}: StationFormProps) {
  const [values, setValues] = useState(() => initialValues(station))
  const [errors, setErrors] = useState<StationFormErrors>({})
  const fieldRefs = useRef<Partial<Record<StationFormField, HTMLInputElement>>>({})
  const isEditing = mode === 'edit'

  const updateField = (field: StationFormField, value: string) => {
    setValues((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isSubmitting) return

    const result = validateStationForm(values)
    if (!result.success) {
      setErrors(result.errors)
      const firstInvalidField = Object.keys(result.errors)[0] as
        | StationFormField
        | undefined
      if (firstInvalidField) fieldRefs.current[firstInvalidField]?.focus()
      return
    }

    setErrors({})
    onSubmit(result.data)
  }

  const fieldError = (field: StationFormField) => errors[field]

  return (
    <section className="station-form-panel" aria-labelledby="station-form-title">
      <div className="station-form-panel__heading">
        <div>
          <h2 id="station-form-title">
            {isEditing ? 'Chỉnh sửa trạm' : 'Tạo trạm mới'}
          </h2>
          <p>
            {isEditing
              ? 'Cập nhật thông tin sẽ hiển thị ngay trong danh sách.'
              : 'Trạm mới được lưu ở trạng thái chưa hoạt động.'}
          </p>
        </div>
        {isEditing && <span className="station-form-panel__station">{station?.name}</span>}
      </div>

      <form
        className="station-form"
        aria-labelledby="station-form-title"
        onSubmit={handleSubmit}
        noValidate
      >
        <div className="form-field">
          <label htmlFor="station-name">Tên trạm</label>
          <input
            id="station-name"
            ref={(element) => {
              if (element) fieldRefs.current.name = element
            }}
            value={values.name}
            onChange={(event) => updateField('name', event.target.value)}
            maxLength={150}
            autoComplete="organization"
            disabled={isSubmitting}
            aria-invalid={Boolean(fieldError('name'))}
            aria-describedby={fieldError('name') ? 'station-name-error' : undefined}
          />
          {fieldError('name') && (
            <span className="field-error" id="station-name-error">
              {fieldError('name')}
            </span>
          )}
        </div>

        <div className="form-field form-field--wide">
          <label htmlFor="station-address">Địa chỉ</label>
          <input
            id="station-address"
            ref={(element) => {
              if (element) fieldRefs.current.address = element
            }}
            value={values.address}
            onChange={(event) => updateField('address', event.target.value)}
            maxLength={500}
            autoComplete="street-address"
            disabled={isSubmitting}
            aria-invalid={Boolean(fieldError('address'))}
            aria-describedby={
              fieldError('address') ? 'station-address-error' : undefined
            }
          />
          {fieldError('address') && (
            <span className="field-error" id="station-address-error">
              {fieldError('address')}
            </span>
          )}
        </div>

        <div className="form-field form-field--wide">
          <strong>Vị trí trạm</strong>
          <p>Bấm vào vị trí trạm trên bản đồ hoặc di chuyển bản đồ rồi chọn tâm.</p>
          <StationMap position={values.latitude && values.longitude ? { latitude: Number(values.latitude), longitude: Number(values.longitude) } : undefined} disabled={isSubmitting}
            onPick={({ latitude, longitude }) => {
              setValues(current => ({ ...current, latitude: String(latitude.toFixed(6)), longitude: String(longitude.toFixed(6)) }))
              setErrors(current => ({ ...current, latitude: undefined, longitude: undefined }))
            }} />
          <p role="status">{values.latitude && values.longitude ? 'Đã chọn vị trí trạm. Bạn có thể chọn lại trên bản đồ.' : 'Chưa chọn vị trí trạm.'}</p>
          {(fieldError('latitude') || fieldError('longitude')) && <span className="field-error" role="alert">Hãy chọn vị trí trạm trên bản đồ.</span>}
        </div>

        {submitError && (
          <div className="form-submit-error" role="alert">
            {submitError}
          </div>
        )}

        <div className="station-form__actions">
          <button
            className="secondary-button"
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
          >
            Hủy
          </button>
          <button className="primary-button" type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Đang lưu…' : isEditing ? 'Lưu thay đổi' : 'Tạo trạm'}
          </button>
        </div>
      </form>
    </section>
  )
}
