import { useEffect, useState, type FormEvent } from 'react'
import type { StationApi } from '../stations/api/stationApi'
import type { Station } from '../stations/model/station'
import { validateStationForm } from '../stations/model/stationValidation'
import { StationMap } from '../../components/maps/StationMap'
import { ownerRequest } from './ownerApi'
import { StationPhoto, Steps } from './OwnerVisuals'
import { stationPhotoMime } from './stationPhoto'

export function StationWizard({
  station,
  api,
  onCancel,
  onSaved,
}: {
  station?: Station
  api: StationApi
  onCancel: () => void
  onSaved: (station: Station) => void
}) {
  const [step, setStep] = useState(0)
  const [values, setValues] = useState({
    name: station?.name ?? '',
    address: station?.address ?? '',
    latitude: station ? String(station.latitude) : '',
    longitude: station ? String(station.longitude) : '',
  })
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [removePhoto, setRemovePhoto] = useState(false)
  const [saved, setSaved] = useState<Station | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (!file) return
    const url = URL.createObjectURL(file)
    const timer = window.setTimeout(() => setPreview(url), 0)
    return () => {
      window.clearTimeout(timer)
      URL.revokeObjectURL(url)
    }
  }, [file])
  function next(event: FormEvent) {
    event.preventDefault()
    const result = validateStationForm(values)
    if (!result.success) {
      setError(Object.values(result.errors).join('. '))
      return
    }
    setError('')
    setStep(1)
  }
  async function save() {
    if (saving) return
    setSaving(true)
    setError('')
    try {
      const result = validateStationForm(values)
      if (!result.success) throw new Error('Hãy kiểm tra lại thông tin trạm.')
      const mime = file ? await stationPhotoMime(file) : null
      // Remember the created record when a photo upload fails; retries never create a duplicate station.
      const record =
        saved ??
        (station
          ? await api.updateStation(station.id, result.data)
          : await api.createStation(result.data))
      setSaved(record)
      if (file)
        await ownerRequest(`/stations/${encodeURIComponent(record.id)}/photo`, {
          method: 'PUT',
          headers: { 'Content-Type': mime! },
          body: file,
        })
      else if (removePhoto && station?.photoUrl)
        await ownerRequest(`/stations/${encodeURIComponent(record.id)}/photo`, {
          method: 'DELETE',
        })
      onSaved(file || removePhoto ? await api.getStation(record.id) : record)
    } catch (err) {
      setError(
        `${saved ? 'Thông tin trạm đã lưu. ' : ''}${err instanceof Error ? err.message : 'Chưa lưu được trạm.'}`,
      )
    } finally {
      setSaving(false)
    }
  }
  function chooseFile(candidate?: File) {
    if (!candidate) return
    if (
      candidate.size > 20 * 1024 * 1024
    ) {
      setError('Chọn ảnh JPEG, PNG hoặc WebP không quá 20 MB.')
      return
    }
    setFile(candidate)
    setRemovePhoto(false)
    setError('')
  }
  const valid = validateStationForm(values)
  const mapStation = valid.success
    ? {
        ...valid.data,
        id: 'location-preview',
        status: 'inactive' as const,
        createdAt: '',
        updatedAt: '',
      }
    : null
  return (
    <section className="owner-page owner-wizard">
      <header className="owner-heading">
        <div>
          <h1>{station ? 'Sửa thông tin trạm' : 'Tạo trạm mới'}</h1>
          <p>Hai bước ngắn để khai báo trạm của bạn.</p>
        </div>
        <button
          className="secondary-button"
          onClick={onCancel}
          disabled={saving}
        >
          Hủy
        </button>
      </header>
      <Steps labels={['Thông tin & vị trí', 'Ảnh & kiểm tra']} step={step} />
      {error && (
        <p role="alert" className="owner-error">
          {error}
        </p>
      )}
      {step === 0 ? (
        <form
          id="owner-station-form"
          className="owner-panel owner-two-column owner-grow"
          onSubmit={next}
        >
          <div>
            <h2>Thông tin trạm</h2>
            {(['name', 'address', 'latitude', 'longitude'] as const).map(
              (key) => (
                <label className="owner-field" key={key}>
                  {
                    {
                      name: 'Tên trạm',
                      address: 'Địa chỉ',
                      latitude: 'Vĩ độ',
                      longitude: 'Kinh độ',
                    }[key]
                  }
                  <input
                    required
                    disabled={saving || !!saved}
                    value={values[key]}
                    maxLength={
                      key === 'name' ? 150 : key === 'address' ? 500 : undefined
                    }
                    onChange={(event) =>
                      setValues({ ...values, [key]: event.target.value })
                    }
                  />
                </label>
              ),
            )}
          </div>
          <div className="owner-location">
            <h2>Vị trí trạm</h2>
            {mapStation ? (
              <StationMap stations={[mapStation]} position={{ latitude: mapStation.latitude, longitude: mapStation.longitude }} disabled={saving || !!saved} onPick={position => setValues(current => ({ ...current, latitude: String(position.latitude), longitude: String(position.longitude) }))} />
            ) : (
              <div className="owner-placeholder">
                Nhập tọa độ để kiểm tra vị trí trên bản đồ.
              </div>
            )}
            <p>Kiểm tra tọa độ đúng vị trí trạm trước khi tiếp tục.</p>
          </div>
        </form>
      ) : (
        <div className="owner-panel owner-grow">
          <h2>Thêm ảnh và kiểm tra lại</h2>
          <p>
            Một ảnh toàn cảnh giúp bạn phân biệt trạm. Bạn có thể bỏ qua ảnh.
          </p>
          <div className="owner-two-column">
            <div>
              <h3>
                Ảnh đại diện <small>· Tùy chọn</small>
              </h3>
              <div className="owner-photo-preview">
                {file && preview ? (
                  <img src={preview} alt="Ảnh trạm đã chọn" />
                ) : (
                  <StationPhoto
                    url={removePhoto ? null : station?.photoUrl}
                    name={values.name}
                  />
                )}
              </div>
              <label className="secondary-button owner-upload">
                {file || station?.photoUrl ? 'Thay ảnh' : 'Chọn ảnh'}
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  disabled={saving}
                  onChange={(event) => chooseFile(event.target.files?.[0])}
                />
              </label>{' '}
              <button
                className="text-button"
                disabled={saving}
                onClick={() => {
                  setFile(null)
                  setRemovePhoto(true)
                }}
              >
                Bỏ ảnh
              </button>
              <p>JPEG, PNG hoặc WebP · tối đa 20 MB, 16 triệu điểm ảnh. Ảnh động dùng khung hình đầu làm ảnh đại diện.</p>
            </div>
            <div className="owner-review">
              <h3>{values.name}</h3>
              <p>{values.address}</p>
              <dl>
                <div>
                  <dt>Vĩ độ</dt>
                  <dd>{values.latitude}</dd>
                </div>
                <div>
                  <dt>Kinh độ</dt>
                  <dd>{values.longitude}</dd>
                </div>
                <div>
                  <dt>Ảnh đại diện</dt>
                  <dd>
                    {file
                      ? 'Đã chọn ảnh'
                      : !removePhoto && station?.photoUrl
                        ? 'Giữ ảnh hiện tại'
                        : 'Không có ảnh'}
                  </dd>
                </div>
              </dl>
              <p>
                {station
                  ? 'Giữ nguyên trạng thái hoạt động của trạm.'
                  : 'Trạm mới chưa hoạt động. Sau khi tạo, bạn có thể thêm trụ và đầu nối.'}
              </p>
              {saved && (
                <p role="status">
                  Thông tin trạm đã lưu. Hãy thử lại ảnh hoặc bỏ qua ảnh để hoàn
                  tất.
                </p>
              )}
            </div>
          </div>
        </div>
      )}
      <footer className="owner-actions">
        <span>
          {step === 0
            ? 'Thông tin được giữ khi chuyển bước.'
            : 'Ảnh tùy chọn — có thể hoàn tất khi chưa có ảnh.'}
        </span>
        <div>
          {step > 0 && !saved && (
            <button
              className="secondary-button"
              disabled={saving}
              onClick={() => setStep(0)}
            >
              Quay lại
            </button>
          )}
          {step === 0 ? (
            <button
              className="primary-button"
              type="submit"
              form="owner-station-form"
            >
              Tiếp tục
            </button>
          ) : (
            <button
              className="primary-button"
              disabled={saving}
              onClick={() => void save()}
            >
              {saving ? 'Đang lưu…' : station ? 'Lưu thay đổi' : 'Tạo trạm'}
            </button>
          )}
        </div>
      </footer>
    </section>
  )
}
