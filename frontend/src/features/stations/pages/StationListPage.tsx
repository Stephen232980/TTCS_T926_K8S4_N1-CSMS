import { useEffect, useMemo, useRef, useState } from 'react'
import { Icon } from '../../../components/icons/Icon'
import { HttpStationApi, StationApiError } from '../api/httpStationApi'
import type { StationApi } from '../api/stationApi'
import { StationFilters } from '../components/StationFilters'
import { StationForm } from '../components/StationForm'
import { StationList } from '../components/StationList'
import type { Station, StationInput, StationStatus } from '../model/station'

const defaultStationApi = new HttpStationApi()

function mutationErrorMessage(error: unknown): string {
  if (error instanceof StationApiError) {
    if (error.status === 401) {
      return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
    }
    if (error.status === 403) {
      return 'Bạn không có quyền thực hiện thao tác này.'
    }
    if (error.status === 422) {
      return 'Dữ liệu chưa hợp lệ. Vui lòng kiểm tra lại các ô nhập.'
    }
  }
  return 'Không thể lưu thông tin trạm. Vui lòng thử lại.'
}

interface StationListPageProps {
  notice: string
  onNotice: (message: string) => void
  onDismissNotice?: () => void
  onOpenStation?: (stationId: string) => void
  api?: StationApi
}

export function StationListPage({
  notice,
  onNotice,
  onDismissNotice = () => undefined,
  onOpenStation = () => undefined,
  api = defaultStationApi,
}: StationListPageProps) {
  const [stations, setStations] = useState<Station[]>([])
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StationStatus | ''>('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [requestVersion, setRequestVersion] = useState(0)
  const [isCreateFormOpen, setIsCreateFormOpen] = useState(false)
  const [editingStation, setEditingStation] = useState<Station | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const submitInFlight = useRef(false)
  const pageSize = 2

  useEffect(() => {
    if (searchInput === search) return
    const timeoutId = window.setTimeout(() => {
      setIsLoading(true)
      setError('')
      setPage(1)
      setSearch(searchInput)
    }, 300)

    return () => window.clearTimeout(timeoutId)
  }, [search, searchInput])

  useEffect(() => {
    const controller = new AbortController()

    api
      .listStations(
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
          !(
            requestError instanceof DOMException &&
            requestError.name === 'AbortError'
          )
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
    setSearchInput(value)
  }

  const handleClearFilters = () => {
    prepareRequest()
    setSearchInput('')
    setSearch('')
    setStatus('')
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

  const openCreateForm = () => {
    setSubmitError('')
    setEditingStation(null)
    setIsCreateFormOpen(true)
  }

  const openEditForm = (station: Station) => {
    setSubmitError('')
    setIsCreateFormOpen(false)
    setEditingStation(station)
  }

  const closeForm = () => {
    if (submitInFlight.current) return
    setSubmitError('')
    setIsCreateFormOpen(false)
    setEditingStation(null)
  }

  const handleCreate = async (input: StationInput) => {
    if (submitInFlight.current) return

    submitInFlight.current = true
    setIsSubmitting(true)
    setSubmitError('')

    try {
      await api.createStation(input)
      setIsCreateFormOpen(false)
      onNotice(`Đã tạo trạm ${input.name}.`)
      prepareRequest()
      setPage(1)
      setRequestVersion((current) => current + 1)
    } catch (requestError: unknown) {
      setSubmitError(mutationErrorMessage(requestError))
    } finally {
      submitInFlight.current = false
      setIsSubmitting(false)
    }
  }

  const handleEdit = async (input: StationInput) => {
    if (submitInFlight.current || editingStation === null) return

    submitInFlight.current = true
    setIsSubmitting(true)
    setSubmitError('')

    try {
      const updatedStation = await api.updateStation(editingStation.id, input)
      setStations((current) =>
        current.map((station) =>
          station.id === updatedStation.id ? updatedStation : station,
        ),
      )
      setEditingStation(null)
      onNotice(`Đã cập nhật trạm ${updatedStation.name}.`)
    } catch (requestError: unknown) {
      setSubmitError(mutationErrorMessage(requestError))
    } finally {
      submitInFlight.current = false
      setIsSubmitting(false)
    }
  }

  return (
    <section className="workspace" id="stations" aria-labelledby="page-title">
      <div className="page-heading">
        <div>
          <h1 id="page-title">Trạm sạc</h1>
          <p>{resultSummary}</p>
        </div>
        <button
          className="primary-button"
          type="button"
          aria-label="Tạo trạm"
          onClick={openCreateForm}
          disabled={isSubmitting}
        >
          <Icon name="plus" />
          <span>Tạo trạm</span>
        </button>
      </div>

      {notice && (
        <div className="notice" role="status">
          <span>{notice}</span>
          <button
            type="button"
            aria-label="Đóng thông báo"
            onClick={onDismissNotice}
          >
            <Icon name="close" />
          </button>
        </div>
      )}

      {isCreateFormOpen && (
        <StationForm
          mode="create"
          isSubmitting={isSubmitting}
          submitError={submitError}
          onSubmit={handleCreate}
          onCancel={closeForm}
        />
      )}

      {editingStation && (
        <StationForm
          key={editingStation.id}
          mode="edit"
          station={editingStation}
          isSubmitting={isSubmitting}
          submitError={submitError}
          onSubmit={handleEdit}
          onCancel={closeForm}
        />
      )}

      <StationFilters
        search={searchInput}
        status={status}
        onSearchChange={handleSearch}
        onStatusChange={handleStatus}
      />

      <StationList
        stations={stations}
        isLoading={isLoading}
        error={error}
        onView={(station) => onOpenStation(station.id)}
        onEdit={openEditForm}
        onClearFilters={handleClearFilters}
        onRetry={handleRetry}
      />

      {!isLoading && !error && totalPages > 0 && (
        <footer className="pagination">
          <span>
            Trang {page} / {totalPages}
          </span>
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
