export function ErrorNotice({
  error,
  onRetry,
}: {
  error: unknown
  onRetry?: () => void
}) {
  if (!error) return null
  return (
    <div className="admin-error" role="alert">
      <span>
        {error instanceof Error ? error.message : String(error)}
        {error instanceof AdminApiError && error.fields.length > 0 && (
          <ul>
            {error.fields.map((field, i) => (
              <li key={i}>{field.message}</li>
            ))}
          </ul>
        )}
      </span>
      {onRetry && <button onClick={onRetry}>Thử lại</button>}
    </div>
  )
}
export function Pagination({
  page,
  totalPages,
  total,
  busy,
  onPage,
}: {
  page: number
  totalPages: number
  total: number
  busy?: boolean
  onPage: (page: number) => void
}) {
  return (
    <footer className="admin-pagination">
      <span>
        {total} bản ghi · Trang {page} / {Math.max(1, totalPages)}
      </span>
      <div className="admin-actions">
        <button disabled={busy || page <= 1} onClick={() => onPage(page - 1)}>
          Trước
        </button>
        <button
          disabled={busy || page >= totalPages}
          onClick={() => onPage(page + 1)}
        >
          Sau
        </button>
      </div>
    </footer>
  )
}
import { AdminApiError } from './adminApi'
