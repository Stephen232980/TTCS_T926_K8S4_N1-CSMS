import { useRef, useState, type FormEvent } from 'react'
import { OwnerApiError } from './ownerApi'
import { stationToday } from './tariffDates'
import { TariffBandsEditor } from './TariffBandsEditor'
import { validateBands, type BandValues } from './tariffBands'

export interface TariffValues {
  bands?: BandValues[]
  effectiveFrom: string
  pricePerKwh: string
  idleFeePerMinute: string
  graceMinutes: string
}

type Field = Exclude<keyof TariffValues, 'bands'>
type NumberField = Exclude<Field, 'effectiveFrom'>

export interface CurrentTariff {
  pricePerKwh: number | string
  idleFeePerMinute: number | string
  graceMinutes: number | string
  effectiveFrom?: string
  bands?: {
    start_min: number
    end_min: number
    energy_rate_vnd_per_kwh: string
    label: string
  }[]
}

interface TariffFormProps {
  initialValues?: TariffValues
  editMode?: boolean
  currentTariff: CurrentTariff | null
  stationTimezone?: string
  hasVersions?: boolean
  tariffToday?: string
  onSave: (values: TariffValues) => Promise<void>
}

const numberFields: { key: NumberField; label: string }[] = [
  { key: 'pricePerKwh', label: 'Đơn giá mỗi kWh (VNĐ)' },
  { key: 'idleFeePerMinute', label: 'Phí chiếm trụ mỗi phút (VNĐ)' },
  { key: 'graceMinutes', label: 'Thời gian ân hạn (phút)' },
]

const MAX_MONEY = BigInt('9223372036854775807')
const MAX_GRACE = BigInt('2147483647')

function validateNumber(field: NumberField, raw: string): string {
  const value = raw.trim()

  if (!value) return 'Không được để trống.'
  if (!/^\d+$/.test(value)) {
    return 'Chỉ được nhập số nguyên không âm.'
  }

  const maximum = field === 'graceMinutes' ? MAX_GRACE : MAX_MONEY

  // Giá trị hợp lệ tối đa có 19 chữ số.
  if (value.replace(/^0+/, '').length > 19) {
    return 'Giá trị vượt phạm vi cho phép.'
  }

  if (BigInt(value) > maximum) {
    return 'Giá trị vượt phạm vi cho phép.'
  }

  return ''
}

function localToday(timeZone?: string): string {
  if (!timeZone) return ''

  try {
    return stationToday(timeZone)
  } catch {
    return ''
  }
}

function nextTariffDay(today: string): string {
  const date = new Date(`${today}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString().slice(0, 10)
}

function validateDate(
  value: string,
  today: string,
  hasVersions: boolean,
): string {
  if (!today) return 'Không xác định được múi giờ của trạm.'
  if (!value) return 'Vui lòng chọn ngày hiệu lực.'

  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return 'Ngày hiệu lực không hợp lệ.'
  }

  const date = new Date(`${value}T00:00:00Z`)

  if (
    Number.isNaN(date.getTime()) ||
    date.toISOString().slice(0, 10) !== value
  ) {
    return 'Ngày hiệu lực không hợp lệ.'
  }

  if (!hasVersions && value !== today)
    return 'Biểu giá đầu tiên phải có hiệu lực hôm nay theo giờ trạm.'
  if (hasVersions && value < nextTariffDay(today))
    return 'Biểu giá tiếp theo phải có hiệu lực từ ngày mai trở đi.'

  return ''
}

function moneyText(value: number | string): string {
  try {
    return BigInt(String(value)).toLocaleString('vi-VN')
  } catch {
    return '—'
  }
}

function apiFieldErrors(detail: unknown): Partial<Record<Field, string>> {
  const errors: Partial<Record<Field, string>> = {}

  if (!Array.isArray(detail)) return errors

  const mapping: Record<string, Field> = {
    effective_from: 'effectiveFrom',
    energy_rate_vnd_per_kwh: 'pricePerKwh',
    idle_rate_vnd_per_minute: 'idleFeePerMinute',
    grace_minutes: 'graceMinutes',
  }

  for (const issue of detail) {
    if (!issue || typeof issue !== 'object') continue

    const item = issue as { loc?: unknown; msg?: unknown }
    if (!Array.isArray(item.loc)) continue

    const apiName = String(item.loc[item.loc.length - 1])
    const field = mapping[apiName]

    if (field) {
      errors[field] =
        typeof item.msg === 'string' ? item.msg : 'Giá trị không hợp lệ.'
    }
  }

  return errors
}

export function TariffForm({
  currentTariff,
  initialValues,
  editMode = false,
  stationTimezone,
  hasVersions = currentTariff !== null,
  tariffToday,
  onSave,
}: TariffFormProps) {
  const today = tariffToday ?? localToday(stationTimezone)
  const minimumDate = today ? (hasVersions ? nextTariffDay(today) : today) : ''

  const [values, setValues] = useState<TariffValues>(
    () =>
      initialValues ?? {
        effectiveFrom: minimumDate,
        pricePerKwh: '',
        idleFeePerMinute: '',
        graceMinutes: '',
      },
  )

  const [touched, setTouched] = useState<Partial<Record<Field, boolean>>>({})

  const [serverErrors, setServerErrors] = useState<
    Partial<Record<Field, string>>
  >({})

  const [multiBand, setMultiBand] = useState(Boolean(initialValues?.bands))
  const [bands, setBands] = useState<BandValues[]>(
    initialValues?.bands ?? [{ start: '00:00', end: '24:00', price: '' }],
  )
  const [bandServerErrors, setBandServerErrors] = useState<string[][]>([])
  const [saving, setSaving] = useState(false)
  const sendingRef = useRef(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const dateError = validateDate(values.effectiveFrom, today, hasVersions)

  const hasError =
    Boolean(dateError) ||
    numberFields.some(
      ({ key }) =>
        (!multiBand || key !== 'pricePerKwh') &&
        Boolean(validateNumber(key, values[key])),
    ) ||
    (multiBand && !validateBands(bands).valid)

  function changeValue(field: Field, value: string) {
    setValues((previous) => ({
      ...previous,
      [field]: value,
    }))

    setTouched((previous) => ({
      ...previous,
      [field]: true,
    }))

    setServerErrors((previous) => ({
      ...previous,
      [field]: '',
    }))

    setSuccess('')
    setError('')
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (sendingRef.current || hasError) return

    sendingRef.current = true
    setSaving(true)
    setError('')
    setSuccess('')
    setServerErrors({})
    setBandServerErrors([])

    try {
      await onSave(multiBand ? { ...values, bands } : values)

      setSuccess(
        `Đã lưu biểu giá vào hệ thống. Ngày hiệu lực: ${values.effectiveFrom}.`,
      )
      setValues((previous) => ({
        ...previous,
        effectiveFrom: editMode ? previous.effectiveFrom : nextTariffDay(today),
      }))
    } catch (caught) {
      if (caught instanceof OwnerApiError) {
        if (caught.status === 409) {
          setServerErrors({
            effectiveFrom:
              'Ngày hiệu lực này đã có biểu giá. Hãy chọn ngày khác.',
          })
        } else if (caught.status === 422) {
          const fieldErrors = apiFieldErrors(caught.detail)
          if (multiBand && Array.isArray(caught.detail)) {
            const issues = bands.map(() => [] as string[])
            for (const issue of caught.detail) {
              if (!issue || typeof issue !== 'object') continue
              const item = issue as {
                loc?: unknown[]
                input_indices?: number[]
                msg?: string
              }
              if (!item.loc?.includes('bands')) continue
              const rows = item.input_indices?.length
                ? item.input_indices
                : typeof item.loc[2] === 'number'
                  ? [item.loc[2]]
                  : bands.map((_, i) => i)
              for (const row of rows)
                if (issues[row])
                  issues[row].push(item.msg ?? 'Khung giờ không hợp lệ.')
            }
            setBandServerErrors(issues)
          }

          if (Object.keys(fieldErrors).length > 0) {
            setServerErrors(fieldErrors)
          } else {
            setError(caught.message)
          }
        } else {
          setError(caught.message)
        }
      } else {
        setError(
          caught instanceof Error
            ? caught.message
            : 'Không thể lưu biểu giá. Vui lòng thử lại.',
        )
      }
    } finally {
      sendingRef.current = false
      setSaving(false)
    }
  }

  const displayedDateError =
    serverErrors.effectiveFrom || (touched.effectiveFrom ? dateError : '')

  return (
    <section className="owner-panel owner-tariff-panel">
      {!editMode && (
        <>
          <h2>Biểu giá đang áp dụng</h2>

          {currentTariff ? (
            <>
              {currentTariff.effectiveFrom && (
                <p className="owner-subtle">
                  Áp dụng từ {currentTariff.effectiveFrom}
                </p>
              )}
              <dl className="owner-tariff-values">
                <div>
                  <dt>Đơn giá mỗi kWh</dt>
                  <dd>
                    {currentTariff.bands && currentTariff.bands.length > 1
                      ? currentTariff.bands.map((band) => (
                          <p key={band.start_min}>
                            {String(Math.floor(band.start_min / 60)).padStart(
                              2,
                              '0',
                            )}
                            :{String(band.start_min % 60).padStart(2, '0')}–
                            {String(Math.floor(band.end_min / 60)).padStart(
                              2,
                              '0',
                            )}
                            :{String(band.end_min % 60).padStart(2, '0')}:{' '}
                            {moneyText(band.energy_rate_vnd_per_kwh)} VNĐ/kWh
                          </p>
                        ))
                      : `${moneyText(currentTariff.pricePerKwh)} VNĐ/kWh`}
                  </dd>
                </div>
                <div>
                  <dt>Phí chiếm trụ mỗi phút</dt>
                  <dd>{moneyText(currentTariff.idleFeePerMinute)} VNĐ/phút</dd>
                </div>
                <div>
                  <dt>Thời gian ân hạn</dt>
                  <dd>{currentTariff.graceMinutes} phút</dd>
                </div>
              </dl>
            </>
          ) : (
            <p className="owner-subtle">Trạm chưa có biểu giá đang áp dụng.</p>
          )}
        </>
      )}
      <h2>{editMode ? 'Sửa phiên bản biểu giá' : 'Khai báo biểu giá'}</h2>

      <p className="owner-subtle">
        Biểu giá đầu tiên có hiệu lực từ hôm nay theo giờ trạm. Phiên bản tiếp
        theo phải có hiệu lực từ ngày mai trở đi. Hệ thống sẽ kiểm tra quy tắc
        này khi lưu.
      </p>

      <form onSubmit={handleSubmit} noValidate>
        <label className="owner-field">
          Ngày hiệu lực
          <input
            type="date"
            value={values.effectiveFrom}
            min={minimumDate || undefined}
            max={!hasVersions ? today || undefined : undefined}
            disabled={saving || !today}
            aria-invalid={Boolean(displayedDateError)}
            onChange={(event) =>
              changeValue('effectiveFrom', event.target.value)
            }
          />
          {displayedDateError && (
            <span className="owner-error" role="alert">
              {displayedDateError}
            </span>
          )}
        </label>
        <label className="owner-field">
          Cách tính giá điện
          <select
            value={multiBand ? 'bands' : 'flat'}
            disabled={saving}
            onChange={(event) => {
              setMultiBand(event.target.value === 'bands')
              setBandServerErrors([])
              setError('')
              setSuccess('')
              if (!multiBand && bands.length === 1 && !bands[0].price)
                setBands([{ ...bands[0], price: values.pricePerKwh }])
            }}
          >
            <option value="flat">Một giá cả ngày</option>
            <option value="bands">Nhiều khung giờ</option>
          </select>
        </label>
        {multiBand && (
          <TariffBandsEditor
            bands={bands}
            disabled={saving}
            serverErrors={bandServerErrors}
            onChange={(next) => {
              setBands(next)
              setBandServerErrors([])
              setError('')
              setSuccess('')
            }}
          />
        )}
        {numberFields
          .filter(({ key }) => !multiBand || key !== 'pricePerKwh')
          .map(({ key, label }) => {
            const clientError = validateNumber(key, values[key])
            const fieldError =
              serverErrors[key] || (touched[key] ? clientError : '')

            return (
              <label className="owner-field" key={key}>
                {label}

                <input
                  type="text"
                  inputMode="numeric"
                  value={values[key]}
                  disabled={saving}
                  aria-invalid={Boolean(fieldError)}
                  onChange={(event) => changeValue(key, event.target.value)}
                />

                {fieldError && (
                  <span className="owner-error" role="alert">
                    {fieldError}
                  </span>
                )}
              </label>
            )
          })}

        {!today && (
          <p className="owner-error" role="alert">
            Không đọc được múi giờ của trạm. Không thể lưu biểu giá.
          </p>
        )}

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
          disabled={saving || hasError || !today}
        >
          {saving ? 'Đang lưu...' : editMode ? 'Lưu thay đổi' : 'Lưu biểu giá'}
        </button>
      </form>
    </section>
  )
}
