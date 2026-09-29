import { useEffect, useMemo, useState } from 'react'
import { Icon } from '../../../components/icons/Icon'
import { MockStationApi } from '../api/mockStationApi'
import type { StationApi } from '../api/stationApi'
import { StationFilters } from '../components/StationFilters'
import { StationList } from '../components/StationList'
import type { Station, StationStatus } from '../model/station'

const defaultStationApi = new MockStationApi()

interface StationListPageProps {
  notice: string
  onNotice: (message: string) => void
  api?: StationApi
}

export function StationListPage({
  notice,
  onNotice,
  api = defaultStationApi,
}: StationListPageProps) {
  const [stations, setStations] = useState<Station[]>([])
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StationStatus | ''>('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [requestVersion, setRequestVersion] = useState(0)
  const pageSize = 2

  useEffect(() => {
    const controller = new AbortController()

    api.listStations(
      { page, pageSize, search, status: status || undefined },
      controller.signal,
    )
      .then((result) => {
        setStations(result.items)
        setTotal(result.total)
        setTotalPages(result.totalPages)
      })
      .catch((requestError: unknown) => {
        if (
          !(requestError instanceof DOMException &&
            requestError.name === 'AbortError')
        ) {
          setError('Không thể tải danh sách trạm. Vui lòng thử lại.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })

    return () => controller.abort()
  }, [api, page, requestVersion, search, status])

  const resultSummary = useMemo(() => {
    if (isLoading) return 'Đang đồng bộ dữ liệu trạm…'
    if (total === 0) return 'Không có trạm phù hợp'
    return `${total} trạm trong phạm vi quản lý`
  }, [isLoading, total])

  const prepareRequest = () => {
    setIsLoading(true)
    setError('')
  }

  const handleSearch = (value: string) => {
    prepareRequest()
    setSearch(value)
    setPage(1)
  }

  const handleStatus = (value: StationStatus | '') => {
    prepareRequest()
    setStatus(value)
    setPage(1)
  }

  const handlePageChange = (nextPage: number) => {
    prepareRequest()
    setPage(nextPage)
  }

  const handleRetry = () => {
    prepareRequest()
    setRequestVersion((current) => current + 1)
  }

  return (
    <section className="workspace" id="stations" aria-labelledby="page-title">
      <div className="page-heading">
        <div><h1 id="page-title">Trạm sạc</h1><p>{resultSummary}</p></div>
        <button
          className="primary-button"
          type="button"
          onClick={() => onNotice('Form tạo trạm sẽ được xây ở bước tiếp theo.')}
        >
          <Icon name="plus" /><span>Tạo trạm</span>
        </button>
      </div>

      {notice && <div className="notice" role="status">{notice}</div>}

      <StationFilters
        search={search}
        status={status}
        onSearchChange={handleSearch}
        onStatusChange={handleStatus}
      />

      <StationList
        stations={stations}
        isLoading={isLoading}
        error={error}
        onEdit={(station) => onNotice(`Chuẩn bị chỉnh sửa ${station.name}.`)}
        onClearFilters={() => { handleSearch(''); handleStatus('') }}
        onRetry={handleRetry}
      />

      {!isLoading && !error && totalPages > 0 && (
        <footer className="pagination">
          <span>Trang {page} / {totalPages}</span>
          <div>
            <button
              type="button"
              disabled={page === 1}
              onClick={() => handlePageChange(page - 1)}
              aria-label="Trang trước"
            >
              <Icon name="chevronLeft" />
            </button>
            <button
              type="button"
              disabled={page === totalPages}
              onClick={() => handlePageChange(page + 1)}
              aria-label="Trang sau"
            >
              <Icon name="chevronRight" />
            </button>
          </div>
        </footer>
      )}
    </section>
  )
}
