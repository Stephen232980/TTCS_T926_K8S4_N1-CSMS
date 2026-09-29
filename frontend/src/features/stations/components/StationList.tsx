import { Icon } from '../../../components/icons/Icon'
import type { Station, StationStatus } from '../model/station'

interface StationListProps {
  stations: Station[]
  isLoading: boolean
  error: string
  onView: (station: Station) => void
  onEdit: (station: Station) => void
  onClearFilters: () => void
  onRetry: () => void
}

function StatusBadge({ status }: { status: StationStatus }) {
  return (
    <span className={`status-badge status-badge--${status}`}>
      <span aria-hidden="true" />
      {status === 'active' ? 'Đang hoạt động' : 'Chưa hoạt động'}
    </span>
  )
}

function StationCards({
  stations,
  onView,
  onEdit,
}: Pick<StationListProps, 'stations' | 'onView' | 'onEdit'>) {
  return (
    <div className="station-cards">
      {stations.map((station) => (
        <article className="station-card" key={station.id}>
          <div className="station-card__header">
            <div><h2>{station.name}</h2><p>{station.address}</p></div>
            <StatusBadge status={station.status} />
          </div>
          <dl>
            <div><dt>Vĩ độ</dt><dd>{station.latitude.toFixed(4)}</dd></div>
            <div><dt>Kinh độ</dt><dd>{station.longitude.toFixed(4)}</dd></div>
          </dl>
          <div className="station-card__actions">
            <button
              className="text-button"
              type="button"
              onClick={() => onView(station)}
            >
              Xem chi tiết
              <Icon name="chevronRight" />
            </button>
            <button
              className="text-button text-button--muted"
              type="button"
              onClick={() => onEdit(station)}
            >
              <Icon name="edit" /> Chỉnh sửa
            </button>
          </div>
        </article>
      ))}
    </div>
  )
}

function StationTable({
  stations,
  onView,
  onEdit,
}: Pick<StationListProps, 'stations' | 'onView' | 'onEdit'>) {
  return (
    <div className="station-table-wrap">
      <table className="station-table">
        <thead>
          <tr>
            <th scope="col">Tên trạm</th>
            <th scope="col">Địa chỉ</th>
            <th scope="col">Tọa độ</th>
            <th scope="col">Trạng thái</th>
            <th scope="col"><span className="sr-only">Thao tác</span></th>
          </tr>
        </thead>
        <tbody>
          {stations.map((station) => (
            <tr key={station.id}>
              <td>
                <button
                  className="station-name-button"
                  type="button"
                  aria-label={`Xem chi tiết ${station.name}`}
                  onClick={() => onView(station)}
                >
                  <strong>{station.name}</strong><span>Mã {station.id}</span>
                </button>
              </td>
              <td>{station.address}</td>
              <td className="coordinates">
                {station.latitude.toFixed(4)}, {station.longitude.toFixed(4)}
              </td>
              <td><StatusBadge status={station.status} /></td>
              <td>
                <button
                  className="icon-button"
                  type="button"
                  aria-label={`Chỉnh sửa ${station.name}`}
                  onClick={() => onEdit(station)}
                >
                  <Icon name="edit" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function StationList({
  stations,
  isLoading,
  error,
  onView,
  onEdit,
  onClearFilters,
  onRetry,
}: StationListProps) {
  return (
    <div className="data-surface" aria-live="polite">
      {isLoading ? (
        <div className="skeleton-list" aria-label="Đang tải danh sách trạm">
          {[0, 1].map((item) => <div className="skeleton-row" key={item} />)}
        </div>
      ) : error ? (
        <div className="state-message state-message--error">
          <h2>Danh sách chưa tải được</h2>
          <p>{error}</p>
          <button type="button" onClick={onRetry}>Thử lại</button>
        </div>
      ) : stations.length === 0 ? (
        <div className="state-message">
          <span className="state-message__icon"><Icon name="search" /></span>
          <h2>Không tìm thấy trạm</h2>
          <p>Thử đổi từ khóa hoặc chọn trạng thái khác.</p>
          <button type="button" onClick={onClearFilters}>Xóa bộ lọc</button>
        </div>
      ) : (
        <>
          <StationTable stations={stations} onView={onView} onEdit={onEdit} />
          <StationCards stations={stations} onView={onView} onEdit={onEdit} />
        </>
      )}
    </div>
  )
}
