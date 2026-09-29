import { useCallback, useEffect, useState } from 'react'
import { AppShell } from './app/AppShell'
import { Icon } from './components/icons/Icon'
import { AuthApiError, type AuthApi } from './features/auth/api/authApi'
import { HttpAuthApi } from './features/auth/api/httpAuthApi'
import type { AuthenticatedUser } from './features/auth/model/auth'
import { LoginPage } from './features/auth/pages/LoginPage'
import { SESSION_UNAUTHORIZED_EVENT } from './features/auth/sessionEvents'
import type { ChargePointApi } from './features/chargePoints/api/chargePointApi'
import type { StationApi } from './features/stations/api/stationApi'
import { StationDetailPage } from './features/stations/pages/StationDetailPage'
import { StationListPage } from './features/stations/pages/StationListPage'
import './App.css'

interface AppProps {
  authApi?: AuthApi
  stationApi?: StationApi
  chargePointApi?: ChargePointApi
}

const defaultAuthApi = new HttpAuthApi()

function App({ authApi = defaultAuthApi, stationApi, chargePointApi }: AppProps) {
  const [authStatus, setAuthStatus] = useState<
    'checking' | 'anonymous' | 'authenticated'
  >('checking')
  const [currentUser, setCurrentUser] = useState<AuthenticatedUser | null>(null)
  const [sessionMessage, setSessionMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null)

  const loadCurrentUser = useCallback(async () => {
    const user = await authApi.getCurrentUser()
    setCurrentUser(user)
    setSessionMessage('')
    setAuthStatus('authenticated')
  }, [authApi])

  useEffect(() => {
    const controller = new AbortController()

    authApi
      .getCurrentUser(controller.signal)
      .then((user) => {
        setCurrentUser(user)
        setAuthStatus('authenticated')
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setCurrentUser(null)
        setAuthStatus('anonymous')
        if (!(error instanceof AuthApiError && error.status === 401)) {
          setSessionMessage(
            'Không thể kiểm tra phiên đăng nhập. Vui lòng đăng nhập lại.',
          )
        }
      })

    return () => controller.abort()
  }, [authApi])

  useEffect(() => {
    const handleUnauthorized = () => {
      setCurrentUser(null)
      setSelectedStationId(null)
      setSessionMessage('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')
      setAuthStatus('anonymous')
    }

    window.addEventListener(SESSION_UNAUTHORIZED_EVENT, handleUnauthorized)
    return () =>
      window.removeEventListener(SESSION_UNAUTHORIZED_EVENT, handleUnauthorized)
  }, [])

  const showPrototypeNotice = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(''), 3200)
  }

  if (authStatus === 'checking') {
    return (
      <main className="auth-checking" aria-live="polite">
        <span className="brand__mark"><Icon name="bolt" /></span>
        <strong>Đang kiểm tra phiên đăng nhập…</strong>
      </main>
    )
  }

  if (authStatus === 'anonymous' || currentUser === null) {
    return (
      <LoginPage
        api={authApi}
        sessionMessage={sessionMessage}
        onAuthenticated={loadCurrentUser}
      />
    )
  }

  return (
    <AppShell
      currentUser={currentUser}
      onUnavailableNavigation={(label) =>
        showPrototypeNotice(`${label} chưa nằm trong prototype T-09.`)
      }
    >
      {selectedStationId ? (
        <StationDetailPage
          key={selectedStationId}
          stationId={selectedStationId}
          onBack={() => setSelectedStationId(null)}
          api={stationApi}
          chargePointApi={chargePointApi}
        />
      ) : (
        <StationListPage
          notice={notice}
          onNotice={showPrototypeNotice}
          onOpenStation={setSelectedStationId}
          api={stationApi}
        />
      )}
    </AppShell>
  )
}

export default App
