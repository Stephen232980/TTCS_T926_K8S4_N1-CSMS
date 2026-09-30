import { Icon } from '../../../components/icons/Icon'
import type { StationStatus } from '../model/station'

interface StationFiltersProps {
  search: string
  status: StationStatus | ''
  onSearchChange: (value: string) => void
  onStatusChange: (value: StationStatus | '') => void
}

export function StationFilters({
  search,
  status,
  onSearchChange,
  onStatusChange,
}: StationFiltersProps) {
  return (
    <div className="toolbar" aria-label="Bộ lọc danh sách trạm">
      <label className="search-field">
        <span className="sr-only">Tìm trạm</span>
        <Icon name="search" />
        <input
          type="search"
          placeholder="Tìm theo tên hoặc địa chỉ…"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
        />
      </label>
      <label className="status-filter">
        <span>Trạng thái</span>
        <select
          value={status}
          onChange={(event) =>
            onStatusChange(event.target.value as StationStatus | '')
          }
        >
          <option value="">Tất cả</option>
          <option value="active">Đang hoạt động</option>
          <option value="inactive">Chưa hoạt động</option>
          <option value="suspended">Tạm ngưng</option>
          <option value="blocked">Đã khóa</option>
        </select>
      </label>
    </div>
  )
}
