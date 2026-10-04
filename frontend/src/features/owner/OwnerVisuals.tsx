import { useEffect, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import { notifySessionUnauthorized } from '../auth/sessionEvents'

export function ConnectionSymbol({ online }: { online?: boolean }) {
  const label = online === undefined ? 'Chưa có dữ liệu kết nối' : online ? 'Trực tuyến' : 'Ngoại tuyến'
  return <svg viewBox="0 0 24 24" role="img" aria-label={label} focusable="false">
    {online === undefined ? <><circle cx="12" cy="12" r="9"/><path d="M9 8a3 3 0 1 1 4 3c-1 .5-1 1-1 3m0 3v1"/></> : online ? <><path d="M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0m-11 4a6 6 0 0 1 8 0"/><circle cx="12" cy="20" r="1"/></> : <><path d="m3 3 18 18M2 8a16 16 0 0 1 4-2m5-2a16 16 0 0 1 11 4M5 12a11 11 0 0 1 3-2m8 1a11 11 0 0 1 3 1m-11 4a6 6 0 0 1 8 0"/><circle cx="12" cy="20" r="1"/></>}
  </svg>
}

export function ConnectorSymbol({ status }: { status: string }) {
  const key = status.toLowerCase()
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {key === 'charging' ? (
        <path d="m13 2-8 11h6l-1 9 8-12h-6Z" />
      ) : key === 'available' ? (
        <path d="m4 12 5 5 11-12" />
      ) : key === 'faulted' ? (
        <>
          <path d="m12 3 10 18H2Z" />
          <path d="M12 8v6m0 3v1" />
        </>
      ) : key === 'reserved' ? (
        <>
          <rect x="5" y="10" width="14" height="11" rx="2" />
          <path d="M8 10V7a4 4 0 0 1 8 0v3" />
        </>
      ) : key === 'unknown' ? (
        <>
          <path d="M9 8a3 3 0 1 1 4 3c-1 .5-1 1-1 3m0 3v1" />
        </>
      ) : (
        <path d="M9 5v14m6-14v14" />
      )}
    </svg>
  )
}
export function ChargerDrawing({ online }: { online?: boolean }) {
  return (
    <svg
      className={`owner-charger-drawing${online ? ' is-online' : ''}`}
      viewBox="0 0 100 120"
      aria-hidden="true"
    >
      <path
        d="M22 36H12v42c0 12 15 12 15 1V58M78 36h10v42c0 12-15 12-15 1V58"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
      />
      <rect
        x="28"
        y="8"
        width="44"
        height="96"
        rx="9"
        fill="#fff"
        stroke="currentColor"
        strokeWidth="2"
      />
      <rect x="34" y="15" width="32" height="29" rx="4" fill="#173b47" />
      <path d="m53 20-8 12h7l-2 9 9-14h-7Z" fill="#b9ebd9" />
      <path
        d="M37 54h26M37 61h19M37 70h26M39 88h22"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M23 105h54"
        stroke="#b2c7ce"
        strokeWidth="5"
        strokeLinecap="round"
      />
    </svg>
  )
}
export function StationPhoto({
  url,
  name,
}: {
  url?: string | null
  name: string
}) {
  const [source, setSource] = useState<{ url: string; blob: string } | null>(
    null,
  )
  const [failure, setFailure] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!url) return
    const controller = new AbortController()
    let blobUrl: string | undefined
    const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
    void fetch(`${base}${url}`, {
      credentials: 'include',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.status === 401) notifySessionUnauthorized()
        if (!response.ok) throw new Error('photo_load_failed')
        const blob = await response.blob()
        if (controller.signal.aborted) return
        blobUrl = URL.createObjectURL(blob)
        setSource({ url, blob: blobUrl })
        setFailure(null)
      })
      .catch(() => { if (!controller.signal.aborted) setFailure(url) })
    return () => {
      controller.abort()
      if (blobUrl) URL.revokeObjectURL(blobUrl)
    }
  }, [url, retry])
  return url && source?.url === url ? (
    <img
      className="owner-station-photo"
      src={source.blob}
      alt={`Ảnh ${name}`}
    />
  ) : (
    <div className="owner-photo-empty">
      <Icon name="station" />
      <span>{url ? failure === url ? 'Không tải được ảnh trạm' : 'Đang tải ảnh trạm…' : 'Chưa có ảnh trạm'}</span>
      {url && failure === url && <button className="text-button" onClick={() => setRetry(value => value + 1)}>Tải lại ảnh</button>}
    </div>
  )
}
export function Steps({ labels, step }: { labels: string[]; step: number }) {
  return (
    <ol className="owner-steps" aria-label="Tiến trình">
      {labels.map((label, index) => (
        <li
          key={label}
          aria-current={index === step ? 'step' : undefined}
          className={index <= step ? 'is-current' : ''}
        >
          <span>{index + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  )
}
