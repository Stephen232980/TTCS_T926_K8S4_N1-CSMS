import { useEffect, useState } from 'react'
import { Icon } from '../../../components/icons/Icon'
import { ChargePointApiError, type ChargePointApi } from '../api/chargePointApi'
import type { ChargePoint, ChargePointPage } from '../model/chargePoint'
import { ChargePointCodeEditor } from './ChargePointCodeEditor'

const statusLabels: Record<string, string> = {
  unknown: 'Chưa rõ',
  offline: 'Ngoại tuyến',
  online: 'Trực tuyến',
  available: 'Sẵn sàng',
  unavailable: 'Không khả dụng',
  faulted: 'Có lỗi',
}

function listErrorMessage(error: unknown): string {
  if (error instanceof ChargePointApiError) {
    if (error.status === 403) return 'Bạn không có quyền xem các trụ của trạm này.'
    if (error.status === 404) return 'Không tìm thấy trạm hoặc trạm đã bị xóa.'
  }
  return 'Không thể tải danh sách trụ sạc. Vui lòng thử lại.'
}

interface ChargePointListProps {
  stationId: string
  api: ChargePointApi
  canManageChargePoints?: boolean
}

export function ChargePointList({
  stationId,
  api,
  canManageChargePoints = false,
}: ChargePointListProps) {
  const [result, setResult] = useState<ChargePointPage | null>(null)
  const [page, setPage] = useState(1)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [requestVersion, setRequestVersion] = useState(0)
  const [editingId, setEditingId] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()

    api
      .listChargePoints(stationId, page, 10, controller.signal)
      .then(setResult)
      .catch((requestError: unknown) => {
        if (
          !(
            requestError instanceof DOMException &&
            requestError.name === 'AbortError'
          )
        ) {
          setError(listErrorMessage(requestError))
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })

    return () => controller.abort()
  }, [api, page, requestVersion, stationId])

  const updateItem = (updated: ChargePoint) => {
    setResult((current) =>
      current
        ? {
            ...current,
            items: current.items.map((item) =>
              item.id === updated.id ? updated : item,
            ),
          }
        : current,
    )
    setEditingId(null)
  }

  const changePage = (nextPage: number) => {
    setIsLoading(true)
    setError('')
    setPage(nextPage)
  }

  const retry = () => {
    setIsLoading(true)
    setError('')
    setRequestVersion((value) => value + 1)
  }

  if (isLoading) {
    return (
      <div className="charge-point-list-state" role="status" aria-live="polite">
        <span className="sr-only">Đang tải danh sách trụ sạc</span>
        <div className="skeleton-row" />
        <div className="skeleton-row" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="charge-point-list-state charge-point-list-state--error" role="alert">
        <strong>Danh sách trụ chưa tải được</strong>
        <span>{error}</span>
        <button type="button" onClick={retry}>
          Thử lại
        </button>
      </div>
    )
  }

  if (!result?.items.length) {
    return (
      <div className="charge-point-list-state">
        <span className="charge-point-list-state__icon"><Icon name="charger" /></span>
        <strong>Trạm chưa có trụ sạc</strong>
        <span>Trụ đầu tiên bạn thêm sẽ xuất hiện tại đây.</span>
      </div>
    )
  }

  return (
    <div className="charge-point-list-wrap">
      <div className="charge-point-list" aria-live="polite">
        {result.items.map((chargePoint) => (
          <article className="charge-point-item" key={chargePoint.id}>
            {canManageChargePoints &&
            chargePoint.codeLockedAt == null &&
            editingId === chargePoint.id ? (
              <ChargePointCodeEditor
                chargePoint={chargePoint}
                api={api}
                onUpdated={updateItem}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <>
                <div className="charge-point-item__identity">
                  <span className="charge-point-item__icon"><Icon name="charger" /></span>
                  <div>
                    <strong>{chargePoint.code}</strong>
                    <span>{chargePoint.name || 'Chưa đặt tên hiển thị'}</span>
                  </div>
                </div>
                <div className="charge-point-item__connectors">
                  <span>{chargePoint.connectors.length} đầu nối</span>
                  <div>
                    {chargePoint.connectors.map((connector) => (
                      <span className="connector-chip" key={connector.id}>
                        #{connector.connectorNumber} · {statusLabels[connector.status] || connector.status}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="charge-point-item__actions">
                  <span className={`charge-point-status charge-point-status--${chargePoint.status}`}>
                    {statusLabels[chargePoint.status] || chargePoint.status}
                  </span>
                  {canManageChargePoints && chargePoint.codeLockedAt == null && (
                    <button
                      className="text-button"
                      type="button"
                      onClick={() => setEditingId(chargePoint.id)}
                    >
                      <Icon name="edit" />
                      Sửa mã
                    </button>
                  )}
                  {chargePoint.codeLockedAt != null && <span>Mã đã khóa</span>}
                </div>
              </>
            )}
          </article>
        ))}
      </div>

      {result.totalPages > 1 && (
        <nav className="pagination" aria-label="Phân trang trụ sạc">
          <span>Trang {result.page} / {result.totalPages} · {result.total} trụ</span>
          <div>
            <button
              type="button"
              aria-label="Trang trụ trước"
              disabled={result.page <= 1}
              onClick={() => changePage(result.page - 1)}
            >
              <Icon name="chevronLeft" />
            </button>
            <button
              type="button"
              aria-label="Trang trụ tiếp theo"
              disabled={result.page >= result.totalPages}
              onClick={() => changePage(result.page + 1)}
            >
              <Icon name="chevronRight" />
            </button>
          </div>
        </nav>
      )}
    </div>
  )
}
