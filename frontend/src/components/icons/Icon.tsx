import type { ReactNode } from 'react'

export type IconName =
  | 'bolt'
  | 'dashboard'
  | 'station'
  | 'charger'
  | 'session'
  | 'report'
  | 'settings'
  | 'search'
  | 'plus'
  | 'chevronLeft'
  | 'chevronRight'
  | 'edit'

const paths: Record<IconName, ReactNode> = {
  bolt: <path d="m13 2-8 11h6l-1 9 8-12h-6l1-8Z" />,
  dashboard: <path d="M4 13h6V4H4v9Zm0 7h6v-3H4v3Zm10 0h6v-9h-6v9Zm0-13h6V4h-6v3Z" />,
  station: <path d="M5 21V6a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v15M3 21h15M8 8h5M8 12h5M19 8l2 2v7a2 2 0 0 1-2 2h-3" />,
  charger: <path d="M7 2h8v11a4 4 0 0 1-8 0V2Zm0 5h8M11 17v5M8 22h6M17 6h2l2 2v4" />,
  session: <path d="M12 8v4l3 2M21 12a9 9 0 1 1-3-6.7M21 3v6h-6" />,
  report: <path d="M4 20V10m6 10V4m6 16v-7m4 7H2" />,
  settings: <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" />,
  search: <path d="m21 21-4.4-4.4M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  chevronLeft: <path d="m15 18-6-6 6-6" />,
  chevronRight: <path d="m9 18 6-6-6-6" />,
  edit: <path d="M13.5 6.5 17.5 10.5M4 20h4l11-11a2.8 2.8 0 0 0-4-4L4 16v4Z" />,
}

export function Icon({ name }: { name: IconName }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {paths[name]}
    </svg>
  )
}
