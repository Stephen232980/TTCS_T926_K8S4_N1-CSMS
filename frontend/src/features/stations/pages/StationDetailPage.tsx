import { useEffect, useState } from 'react'
import { Icon } from '../../../components/icons/Icon'
import type { ChargePointApi } from '../../chargePoints/api/chargePointApi'
import { HttpChargePointApi } from '../../chargePoints/api/httpChargePointApi'
import { ChargePointForm } from '../../chargePoints/components/ChargePointForm'
import { ChargePointCodeEditor } from '../../chargePoints/components/ChargePointCodeEditor'
import type { ChargePoint } from '../../chargePoints/model/chargePoint'
import { HttpStationApi, StationApiError } from '../api/httpStationApi'
import type { StationApi } from '../api/stationApi'
import type { Station } from '../model/station'

const defaultStationApi = new HttpStationApi()
const defaultChargePointApi = new HttpChargePointApi()

const stationStatusLabels: Record<Station['status'], string> = {
  active: 'Đang hoạt động',
  inactive: 'Chưa hoạt động',
  suspended: 'Tạm ngưng',
  blocked: 'Đã khóa',
}

function detailErrorMessage(error: unknown): string {
  if (error instanceof StationApiError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
    if (error.status === 403) return 'Bạn không có quyền xem trạm này.'
    if (error.status === 404) return 'Không tìm thấy trạm hoặc trạm đã bị xóa.'
  }
  return 'Không thể tải chi tiết trạm. Vui lòng thử lại.'
}

interface StationDetailPageProps {
  stationId: string
  onBack: () => void
  api?: StationApi
  chargePointApi?: ChargePointApi
}

export function StationDetailPage({
  stationId,
  onBack,
  api = defaultStationApi,
  chargePointApi = defaultChargePointApi,
}: StationDetailPageProps) {
  const [station, setStation] = useState<Station | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [requestVersion, setRequestVersion] = useState(0)
  const [createdChargePoint, setCreatedChargePoint] = useState<ChargePoint | null>(
    null,
  )
  const [isEditingChargePointCode, setIsEditingChargePointCode] = useState(false)

  useEffect(() => {
    const controller = new AbortController()

    api
      .getStation(stationId, controller.signal)
      .then(setStation)
      .catch((requestError: unknown) => {
        if (
          !(
            requestError instanceof DOMException &&
            requestError.name === 'AbortError'
          )
        ) {
          setError(detailErrorMessage(requestError))
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })

    return () => controller.abort()
  }, [api, requestVersion, stationId])

  const handleRetry = () => {
    setIsLoading(true)
    setError('')
    setRequestVersion((current) => current + 1)
  }

  return (
    <section className="workspace station-detail" aria-labelledby="page-title">
      <button className="back-button" type="button" onClick={onBack}>
        <Icon name="chevronLeft" />
        Quay lại danh sách trạm
      </button>

      {isLoading ? (
        <div
          className="station-detail__loading"
          role="status"
          aria-label="Đang tải chi tiết trạm"
          aria-busy="true"
        >
          <span className="sr-only">Đang tải chi tiết trạm</span>
          <div className="skeleton-row" />
          <div className="skeleton-row" />
        </div>
      ) : error ? (
        <div className="state-message state-message--error" role="alert">
          <h1 id="page-title">Chi tiết trạm chưa tải được</h1>
          <p>{error}</p>
          <button
            type="button"
            onClick={handleRetry}
          >
            Thử lại
          </button>
        </div>
      ) : station ? (
        <>
          <header className="station-detail__heading">
            <div>
              <h1 id="page-title">{station.name}</h1>
              <p>{station.address}</p>
            </div>
            <span className={`status-badge status-badge--${station.status}`}>
              <span aria-hidden="true" />
              {stationStatusLabels[station.status]}
            </span>
          </header>

          <dl className="station-detail__facts">
            <div><dt>Mã trạm</dt><dd>{station.id}</dd></div>
            <div><dt>Vĩ độ</dt><dd>{station.latitude.toFixed(6)}</dd></div>
            <div><dt>Kinh độ</dt><dd>{station.longitude.toFixed(6)}</dd></div>
          </dl>

          <section className="station-detail__charge-points" aria-labelledby="charge-points-title">
            <div className="station-detail__section-heading">
              <h2 id="charge-points-title">Trụ sạc và đầu nối</h2>
              <p>Thêm trụ sạc thuộc trạm này và khai báo số đầu nối đi kèm.</p>
            </div>
            {createdChargePoint && (
              <div
                className="charge-point-created"
                role={isEditingChargePointCode ? undefined : 'status'}
              >
                {isEditingChargePointCode ? (
                  <ChargePointCodeEditor
                    chargePoint={createdChargePoint}
                    api={chargePointApi}
                    onUpdated={(updated) => {
                      setCreatedChargePoint(updated)
                      setIsEditingChargePointCode(false)
                    }}
                    onCancel={() => setIsEditingChargePointCode(false)}
                  />
                ) : (
                  <>
                    <div>
                      <strong>Đã thêm trụ {createdChargePoint.code}</strong>
                      <span>{createdChargePoint.connectors.length} đầu nối, trạng thái ban đầu chưa rõ</span>
                    </div>
                    <div className="charge-point-created__actions">
                      <span className="status-badge status-badge--inactive">Ngoại tuyến</span>
                      <button
                        className="text-button"
                        type="button"
                        disabled={createdChargePoint.codeLockedAt != null}
                        onClick={() => setIsEditingChargePointCode(true)}
                      >
                        {createdChargePoint.codeLockedAt != null
                          ? 'Mã đã khóa'
                          : 'Sửa mã trụ'}
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
            <ChargePointForm
              stationId={station.id}
              api={chargePointApi}
              onCreated={setCreatedChargePoint}
            />
          </section>
        </>
      ) : null}
    </section>
  )
}
