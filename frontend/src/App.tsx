import { DriverMapPage } from './features/driver/DriverMapPage'
import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { OcppConnectionsPage } from './features/ocpp/OcppConnectionsPage'
import { ChargingSessionsPage } from './features/charging/ChargingSessionsPage'
import { AppShell } from './app/AppShell'
import { Icon } from './components/icons/Icon'
import { AuthApiError, type AuthApi } from './features/auth/api/authApi'
import { HttpAuthApi } from './features/auth/api/httpAuthApi'
import type { AuthenticatedUser } from './features/auth/model/auth'
import { getHomeRole, getPermissions } from './features/auth/model/permissions'
import { LoginPage } from './features/auth/pages/LoginPage'
import { RoleHomePage } from './features/auth/pages/RoleHomePage'
import { SESSION_UNAUTHORIZED_EVENT } from './features/auth/sessionEvents'
import type { ChargePointApi } from './features/chargePoints/api/chargePointApi'
import type { StationApi } from './features/stations/api/stationApi'
import { StationDetailPage } from './features/stations/pages/StationDetailPage'
import { StationListPage } from './features/stations/pages/StationListPage'
import './App.css'
import { WorkspaceChooser } from './features/auth/pages/WorkspaceChooser'
import { HttpStationApi } from './features/stations/api/httpStationApi'
import { HttpChargePointApi } from './features/chargePoints/api/httpChargePointApi'
import { OwnerWorkspace } from './features/owner/OwnerWorkspace'
const OperatorWorkspace = lazy(() => import('./features/operator/OperatorWorkspace').then(module => ({ default: module.OperatorWorkspace })))
const DriverWorkspace = lazy(() => import('./features/driver/DriverWorkspace').then(module => ({ default: module.DriverWorkspace })))
const AdminWorkspace = lazy(() =>
  import('./features/admin/AdminWorkspace').then(module => ({ default: module.AdminWorkspace })),
)
const AccountantWorkspace = lazy(() =>
  import('./features/accountant/AccountantWorkspace').then(module => ({ default: module.AccountantWorkspace })),
)

interface AppProps {
  authApi?: AuthApi
  stationApi?: StationApi
  chargePointApi?: ChargePointApi
}

const defaultAuthApi = new HttpAuthApi()
const opsStationApi = new HttpStationApi(undefined, undefined, 'ops')
const opsChargePointApi = new HttpChargePointApi(undefined, 'ops')

function App({
  authApi = defaultAuthApi,
  stationApi,
  chargePointApi,
}: AppProps) {
  const [authStatus, setAuthStatus] = useState<
    'checking' | 'anonymous' | 'authenticated'
  >('checking')
  const [currentUser, setCurrentUser] = useState<AuthenticatedUser | null>(null)
  const [areaRole, setAreaRole] = useState<string | null>(null)
  const [sessionMessage, setSessionMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [noticeVersion, setNoticeVersion] = useState(0)
  const [selectedStationId, setSelectedStationId] = useState<string | null>(
    null,
  )
  const [workspace, setWorkspace] = useState<
    'stations' | 'ocpp' | 'charging' | 'driver'
  >('stations')

  const loadCurrentUser = useCallback(async () => {
    const user = await authApi.getCurrentUser()
    setAreaRole(null)
    setCurrentUser(user)
    setSessionMessage('')
    setAuthStatus('authenticated')
  }, [authApi])

  useEffect(() => {
    const controller = new AbortController()

    authApi
      .getCurrentUser(controller.signal)
      .then((user) => {
        setAreaRole(null)
        setCurrentUser(user)
        setAuthStatus('authenticated')
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setAreaRole(null)
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
      setAreaRole(null)
      setCurrentUser(null)
      setSelectedStationId(null)
      setSessionMessage('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')
      setAuthStatus('anonymous')
    }

    window.addEventListener(SESSION_UNAUTHORIZED_EVENT, handleUnauthorized)
    return () =>
      window.removeEventListener(SESSION_UNAUTHORIZED_EVENT, handleUnauthorized)
  }, [])

  useEffect(() => {
    if (!notice) return
    const timeoutId = window.setTimeout(() => setNotice(''), 5000)
    return () => window.clearTimeout(timeoutId)
  }, [notice, noticeVersion])

  const showPrototypeNotice = (message: string) => {
    setNotice(message)
    setNoticeVersion((current) => current + 1)
  }

  const handleLogout = async () => {
    await authApi.logout()
    setAreaRole(null)
    setCurrentUser(null)
    setSelectedStationId(null)
    setWorkspace('stations')
    setSessionMessage('Bạn đã đăng xuất an toàn.')
    setAuthStatus('anonymous')
  }

  if (authStatus === 'checking') {
    return (
      <main className="auth-checking" aria-live="polite">
        <span className="brand__mark">
          <Icon name="bolt" />
        </span>
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

  const primaryRole = areaRole && currentUser.roles.includes(areaRole)
    ? areaRole : getHomeRole(currentUser)
  const chooseArea = () => {
    setAreaRole('')
    setSelectedStationId(null)
    setWorkspace('stations')
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  }
  if (areaRole === '' || !primaryRole) {
    return (
      <WorkspaceChooser user={currentUser} api={authApi} onLogout={handleLogout}
        onChoose={(role, updated) => {
          if (updated) setCurrentUser(updated)
          setAreaRole(role)
          setSelectedStationId(null)
          setWorkspace('stations')
          window.history.replaceState(null, '', role === 'admin' ? '#admin-accounts' : '#stations')
        }}
      />
    )
  }
  const workspaceUser = { ...currentUser, roles: [primaryRole], defaultRole: primaryRole }
  const permissions = getPermissions(workspaceUser)
  const switchArea = currentUser.roles.length > 1 ? chooseArea : undefined

  if (primaryRole === 'admin') {
    return (
      <Suspense fallback={<main className="auth-checking" role="status">Đang tải khu vực quản trị…</main>}>
        <AdminWorkspace currentUser={workspaceUser} onLogout={handleLogout} onExit={switchArea} />
      </Suspense>
    )
  }

  if (primaryRole === 'operator') {
    return <Suspense fallback={<main className="auth-checking" role="status">Đang tải khu vực vận hành…</main>}><OperatorWorkspace currentUser={workspaceUser} onLogout={handleLogout} onExit={switchArea} /></Suspense>
  }

  if (primaryRole === 'station_owner') {
    return (
      <OwnerWorkspace
        currentUser={workspaceUser}
        onLogout={handleLogout}
        stationApi={stationApi}
        chargePointApi={chargePointApi}
        onAdmin={switchArea}
      />
    )
  }

  if (primaryRole === 'driver') {
    return <Suspense fallback={<main className="auth-checking" role="status">Đang tải khu vực tài xế…</main>}><DriverWorkspace currentUser={workspaceUser} onLogout={handleLogout} onExit={switchArea} /></Suspense>
  }

  if (primaryRole === 'accountant') {
    return (
      <Suspense fallback={<main className="auth-checking" role="status">Đang tải khu vực kế toán…</main>}>
        <AccountantWorkspace currentUser={workspaceUser} onLogout={handleLogout} onExit={switchArea} />
      </Suspense>
    )
  }

  return (
    <AppShell
      currentUser={workspaceUser}
      onLogout={handleLogout}
      onNavigateHome={() => {
        setWorkspace('stations')
        setSelectedStationId(null)
      }}
      navigationActive={workspace === 'stations'}
    >
      {switchArea && <button className="text-button" onClick={switchArea}>Đổi khu vực</button>}
      {permissions.canViewStations && (
        <nav className="workspace-switch" aria-label="Khu vực vận hành">
          <button
            className={
              workspace === 'stations'
                ? 'text-button workspace-switch__active'
                : 'text-button'
            }
            aria-pressed={workspace === 'stations'}
            onClick={() => setWorkspace('stations')}
          >
            Trạm sạc
          </button>
          <button
            className={
              workspace === 'ocpp'
                ? 'text-button workspace-switch__active'
                : 'text-button'
            }
            aria-pressed={workspace === 'ocpp'}
            onClick={() => setWorkspace('ocpp')}
          >
            Kết nối trụ
          </button>
          <button
            className={
              workspace === 'charging'
                ? 'text-button workspace-switch__active'
                : 'text-button'
            }
            aria-pressed={workspace === 'charging'}
            onClick={() => setWorkspace('charging')}
          >
            Phiên sạc
          </button>
          {permissions.canUseDriver && (
            <button
              className={
                workspace === 'driver'
                  ? 'text-button workspace-switch__active'
                  : 'text-button'
              }
              aria-pressed={workspace === 'driver'}
              onClick={() => setWorkspace('driver')}
            >
              Tài xế
            </button>
          )}
        </nav>
      )}
      {!permissions.canViewStations && permissions.canViewCharging ? (
        <ChargingSessionsPage area="accounting" canManage={false} canClose={false} />
      ) : !permissions.canViewStations ? (
        primaryRole === 'driver' ? (
          <DriverMapPage />
        ) : (
          <RoleHomePage role={primaryRole} />
        )
      ) : workspace === 'driver' && permissions.canUseDriver ? (
        <DriverMapPage />
      ) : workspace === 'ocpp' ? (
        <OcppConnectionsPage
          area="ops"
          canControl={permissions.canControlChargers}
          canAudit={permissions.canViewControlAudit}
        />
      ) : workspace === 'charging' ? (
        <ChargingSessionsPage
          area="ops"
          canManage={permissions.canViewStations}
          canClose={permissions.canCloseChargingSessions}
        />
      ) : selectedStationId ? (
        <StationDetailPage
          key={selectedStationId}
          stationId={selectedStationId}
          onBack={() => setSelectedStationId(null)}
          api={stationApi ?? opsStationApi}
          chargePointApi={chargePointApi ?? opsChargePointApi}
          canManageChargePoints={permissions.canManageChargePoints}
        />
      ) : (
        <StationListPage
          notice={notice}
          onNotice={showPrototypeNotice}
          onDismissNotice={() => setNotice('')}
          onOpenStation={setSelectedStationId}
          api={stationApi ?? opsStationApi}
          canManageStations={permissions.canManageStations}
        />
      )}
    </AppShell>
  )
}

export default App
