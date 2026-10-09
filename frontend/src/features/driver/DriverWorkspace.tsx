import { useCallback, useEffect, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import type { MapStation } from '../../components/maps/StationMap'
import type { AuthenticatedUser } from '../auth/model/auth'
import { DriverCharging } from './DriverCharging'
import { DriverMapPage } from './DriverMapPage'
import { WalletTopUpPage } from './WalletTopUpPage'
import './driver.css'

type Area = 'session' | 'stations' | 'wallet'
const hashArea = (): Area => {
  if (window.location.hash === '#driver-wallet') {
    return 'wallet'
  }

  if (window.location.hash === '#driver-stations') {
    return 'stations'
  }

  return 'session'
}

export function DriverWorkspace({ currentUser, onLogout, onExit }: {
  currentUser: AuthenticatedUser
  onLogout: () => Promise<void>
  onExit?: () => void
}) {
  const [area, setArea] = useState<Area>(hashArea)
  const [mapOpened, setMapOpened] = useState(() => hashArea() === 'stations')
  const [station, setStation] = useState<MapStation>()
  const [showStart, setShowStart] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  useEffect(() => {
    const change = () => {
      const next = hashArea()
      setArea(next)
      if (next === 'stations') setMapOpened(true)
      setShowStart(false)
    }
    window.addEventListener('hashchange', change)
    return () => window.removeEventListener('hashchange', change)
  }, [])
  const navigate = useCallback((next: Area) => {
    setArea(next)
    setShowStart(false)
    if (next === 'stations') setMapOpened(true)
    window.history.replaceState(null, '', `#driver-${next}`)
  }, [])
  const showStations = useCallback(() => navigate('stations'), [navigate])
  const sessionStarted = useCallback(() => navigate('session'), [navigate])
  async function logout() {
    setLoggingOut(true)
    setLogoutError('')
    try { await onLogout() }
    catch { setLogoutError('Chưa đăng xuất được. Hãy thử lại.') }
    finally { setLoggingOut(false) }
  }
  return <div className="driver-shell">
    <aside className="driver-sidebar">
      <a className="driver-brand" href="#driver-session" onClick={event => { event.preventDefault(); navigate('session') }}><Icon name="station" /><strong>CSMS</strong><span>Tài xế</span></a>
      <nav className="driver-navigation" aria-label="Khu vực tài xế">
        {([{ key: 'session', label: 'Phiên sạc của bạn', icon: 'session' }, { key: 'stations', label: 'Tìm trạm', icon: 'station' },{ key: 'wallet', label: 'Ví của tôi', icon: 'session' }] as const).map(item => <a key={item.key} href={`#driver-${item.key}`} aria-current={area === item.key ? 'page' : undefined} onClick={event => { event.preventDefault(); navigate(item.key) }}><Icon name={item.icon} /><span>{item.label}</span></a>)}
      </nav>
      <footer className="driver-account">
        <details><summary><Icon name="settings" /><span>Tài khoản</span></summary><div><strong>Tài xế</strong><span title={currentUser.email}>{currentUser.email}</span>{onExit && <button onClick={onExit}>Đổi khu vực</button>}{logoutError && <p role="alert">{logoutError}</p>}<button disabled={loggingOut} onClick={() => void logout()}><Icon name="logout" />{loggingOut ? 'Đang đăng xuất…' : 'Đăng xuất'}</button></div></details>
      </footer>
    </aside>
    <main className="driver-main">

<header className="driver-heading">
  <h1>
    {area === 'wallet'
      ? 'Ví của tôi'
      : area === 'session'
        ? 'Phiên sạc của bạn'
        : showStart
          ? 'Bắt đầu sạc'
          : 'Tìm trạm sạc'}
  </h1>

  <p>
    {area === 'wallet'
      ? 'Nạp tiền vào ví và theo dõi trạng thái giao dịch.'
      : area === 'session'
        ? 'Theo dõi điện năng và thời gian từ trụ đang sạc.'
        : showStart
          ? 'Chọn đúng đầu nối, cắm súng vào xe rồi gửi yêu cầu.'
          : 'Xem vị trí trạm và tìm nơi sạc phù hợp.'}
  </p>
</header>

      <div className="driver-return" hidden={!showStart || area !== 'stations'}><button className="secondary-button" onClick={() => setShowStart(false)}><Icon name="chevronLeft" />Quay lại bản đồ và danh sách</button></div>
      <DriverCharging stationId={station?.id} stationName={station?.name} showSession={area === 'session'} showConnectors={area === 'stations' && showStart} onFindStations={showStations} onSessionStarted={sessionStarted} />
      {mapOpened && <div className="driver-map-container" hidden={area !== 'stations' || showStart}><DriverMapPage selectedStationId={station?.id} onOpenStation={selected => { setStation(selected); setShowStart(true) }} /></div>}

{area === 'wallet' && (
  <WalletTopUpPage
    onTopUp={async () => {
      throw new Error('Chưa kết nối API nạp tiền')
    }}
  />
)}
    </main>
  </div>
}
