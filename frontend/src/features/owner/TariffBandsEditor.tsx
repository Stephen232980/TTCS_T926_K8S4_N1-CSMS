import { useId } from 'react'
import { clockText, validateBands, type BandValues } from './tariffBands'

export function TariffBandsEditor({
  bands,
  onChange,
  disabled,
  serverErrors,
}: {
  bands: BandValues[]
  onChange: (bands: BandValues[]) => void
  disabled: boolean
  serverErrors: string[][]
}) {
  const id = useId()
  const { errors, segments, valid } = validateBands(bands)
  return (
    <fieldset className="owner-tariff-bands" disabled={disabled}>
      <legend>Khung giờ và đơn giá</legend>
      <p className="owner-subtle">
        Giờ theo múi giờ trạm, dạng HH:MM. Dùng 24:00 cho cuối ngày. Khung vắt
        đêm sẽ được tách thành hai dòng sau khi lưu.
      </p>
      {bands.map((band, index) => {
        const issues = [
          ...new Set([...errors[index], ...(serverErrors[index] ?? [])]),
        ]
        return (
          <div className="owner-band-row" key={index}>
            <strong>Khung {index + 1}</strong>
            <div className="owner-band-fields">
              {(['start', 'end', 'price'] as const).map((field) => (
                <label className="owner-field" key={field}>
                  {field === 'start'
                    ? 'Từ giờ'
                    : field === 'end'
                      ? 'Đến giờ'
                      : 'Đơn giá (VNĐ/kWh)'}
                  <input
                    aria-label={`${field === 'start' ? 'Từ giờ' : field === 'end' ? 'Đến giờ' : 'Đơn giá'} khung ${index + 1}`}
                    value={band[field]}
                    placeholder={
                      field === 'price'
                        ? '3500'
                        : field === 'start'
                          ? '00:00'
                          : '24:00'
                    }
                    inputMode={field === 'price' ? 'numeric' : 'text'}
                    aria-invalid={issues.length > 0}
                    aria-describedby={
                      issues.length ? `${id}-${index}` : undefined
                    }
                    onChange={(event) =>
                      onChange(
                        bands.map((row, i) =>
                          i === index
                            ? { ...row, [field]: event.target.value }
                            : row,
                        ),
                      )
                    }
                  />
                </label>
              ))}
              <button
                className="secondary-button"
                type="button"
                aria-label={`Xoá khung ${index + 1}`}
                onClick={() => onChange(bands.filter((_, i) => i !== index))}
              >
                Xoá khung
              </button>
            </div>
            {issues.length > 0 && (
              <p id={`${id}-${index}`} className="owner-error" role="alert">
                {issues.join(' ')}
              </p>
            )}
          </div>
        )
      })}
      {bands.length === 0 && (
        <p className="owner-error" role="alert">
          Thêm ít nhất một khung phủ kín 24 giờ.
        </p>
      )}
      <button
        className="secondary-button"
        type="button"
        disabled={bands.length >= 1440}
        onClick={() => onChange([...bands, { start: '', end: '', price: '' }])}
      >
        Thêm khung giờ
      </button>
      <div className="owner-band-preview">
        <h3>Xem trước 24 giờ</h3>
        <svg
          viewBox="0 0 1440 70"
          role="img"
          aria-label="Bản xem trước độ phủ biểu giá trong 24 giờ"
          preserveAspectRatio="none"
        >
          {segments.map((segment) => (
            <rect
              key={segment.start}
              x={segment.start}
              y="4"
              width={segment.end - segment.start}
              height="56"
              className={`owner-band-${segment.rows.length === 0 ? 'gap' : segment.rows.length > 1 ? 'overlap' : 'covered'}`}
            >
              <title>
                {clockText(segment.start)}–{clockText(segment.end)}:{' '}
                {segment.rows.length === 0
                  ? 'Khoảng hở'
                  : segment.rows.length > 1
                    ? 'Khoảng chồng'
                    : `Khung ${segment.rows[0] + 1}`}
              </title>
            </rect>
          ))}
        </svg>
        <div className="owner-band-axis">
          <span>00:00</span>
          <span>06:00</span>
          <span>12:00</span>
          <span>18:00</span>
          <span>24:00</span>
        </div>
        <p className="owner-subtle">
          Xanh: đã phủ · Vàng: khoảng hở · Đỏ: khoảng chồng
        </p>
        <p role="status">
          {valid
            ? 'Các khung phủ kín 24 giờ, không chồng lấn.'
            : 'Chưa thể lưu. Sửa các dòng báo lỗi để phủ kín 24 giờ.'}
        </p>
      </div>
    </fieldset>
  )
}
