import { useCallback, useEffect, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import type { MapStation } from '../../components/maps/StationMap'
import type { AuthenticatedUser } from '../auth/model/auth'
import { DriverCharging } from './DriverCharging'
import { DriverMapPage } from './DriverMapPage'
import { DriverWalletPage } from './DriverWalletPage'
import { WalletTopUpPage } from './WalletTopUpPage'
import { WalletTopUpReturn } from './WalletTopUpReturn'
import { createWalletTopUp, getWalletTopUp, refreshDriverWallet } from './walletTopUpApi'
import { readTopUpReturn } from './walletTopUpReturnUrl'
import './driver.css'

type Area = 'session' | 'stations' | 'wallet'
const hashArea = (): Area => {
  if (readTopUpReturn(window.location).isReturn) return 'wallet'
  if (window.location.hash === '#driver-wallet') return 'wallet'
  if (window.location.hash === '#driver-stations') return 'stations'
  return 'session'
}

export function DriverWorkspace({ currentUser, onLogout, onExit, navigateToPayment }: {
  currentUser: AuthenticatedUser
  onLogout: () => Promise<void>
  onExit?: () => void
  navigateToPayment?: (url: string) => void
}) {
  const [area, setArea] = useState<Area>(hashArea)
  const [returnLocation, setReturnLocation] = useState(() => readTopUpReturn(window.location))
  const [manualOrderId, setManualOrderId] = useState('')
  const showingReturn = returnLocation.isReturn || Boolean(manualOrderId)
  const returnOrderId = manualOrderId || returnLocation.orderId
  const [mapOpened, setMapOpened] = useState(() => hashArea() === 'stations')
  const [station, setStation] = useState<MapStation>()
  const [showStart, setShowStart] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState('')

  useEffect(() => {
    const change = () => {
      const next = hashArea()
      setArea(next)
      setReturnLocation(readTopUpReturn(window.location))
      setManualOrderId('')
      if (next === 'stations') setMapOpened(true)
      setShowStart(false)
    }
    window.addEventListener('hashchange', change)
    window.addEventListener('popstate', change)
    return () => { window.removeEventListener('hashchange', change); window.removeEventListener('popstate', change) }
  }, [])

  const navigate = useCallback((next: Area) => {
    setArea(next)
    setReturnLocation({ isReturn: false, orderId: '' })
    setManualOrderId('')
    setShowStart(false)
    if (next === 'stations') setMapOpened(true)
    const safePath = window.location.pathname.replace(/\/(?:driver\/)?wallet\/topup\/return\/?$/i, '/')
    window.history.replaceState(null, '', `${safePath}#driver-${next}`)
  }, [])
  const showStations = useCallback(() => navigate('stations'), [navigate])
  const checkTopUpOrder = useCallback((orderId: string) => {
    setArea('wallet')
    setManualOrderId(orderId)
    setReturnLocation({ isReturn: true, orderId })
    window.history.replaceState(null, '', `#driver-wallet-return?order_code=${encodeURIComponent(orderId)}`)
  }, [])
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
        {([
          { key: 'session', label: 'Phiên sạc của bạn', icon: 'session' },
          { key: 'stations', label: 'Tìm trạm', icon: 'station' },
          { key: 'wallet', label: 'Ví của bạn', icon: 'wallet' },
        ] as const).map(item => <a key={item.key} href={`#driver-${item.key}`} aria-current={area === item.key ? 'page' : undefined} onClick={event => { event.preventDefault(); navigate(item.key) }}><Icon name={item.icon} /><span>{item.label}</span></a>)}
      </nav>
      <footer className="driver-account">
        <details><summary><Icon name="settings" /><span>Tài khoản</span></summary><div><strong>Tài xế</strong><span title={currentUser.email}>{currentUser.email}</span>{onExit && <button onClick={onExit}>Đổi khu vực</button>}{logoutError && <p role="alert">{logoutError}</p>}<button disabled={loggingOut} onClick={() => void logout()}><Icon name="logout" />{loggingOut ? 'Đang đăng xuất…' : 'Đăng xuất'}</button></div></details>
      </footer>
    </aside>
    <main className="driver-main">
      <header className="driver-heading">
        <h1>
          {area === 'session'
            ? 'Phiên sạc của bạn'
            : area === 'wallet'
              ? showingReturn ? 'Trạng thái nạp tiền' : 'Ví tiền của bạn'
              : showStart
                ? 'Bắt đầu sạc'
                : 'Tìm trạm sạc'}
        </h1>
        <p>
          {area === 'session'
            ? 'Theo dõi điện năng và thời gian từ trụ đang sạc.'
            : area === 'wallet'
              ? showingReturn
                ? 'Theo dõi trạng thái giao dịch nạp tiền của bạn.'
                : 'Theo dõi số dư, lịch sử giao dịch và nạp tiền vào ví.'
              : showStart
                ? 'Chọn đúng đầu nối, cắm súng vào xe rồi gửi yêu cầu.'
                : 'Xem vị trí trạm và tìm nơi sạc phù hợp.'}
        </p>
      </header>
      {area === 'wallet' ? (
        showingReturn ? (
          <WalletTopUpReturn
            transactionId={returnOrderId}
            getStatus={getWalletTopUp}
            onSucceeded={refreshDriverWallet}
            onBack={() => navigate('wallet')}
          />
        ) : (
          <div className="driver-wallet-stack">
            <DriverWalletPage />
            <WalletTopUpPage
              onTopUp={createWalletTopUp}
              onCheckOrder={checkTopUpOrder}
              onRedirect={navigateToPayment}
            />
          </div>
        )
      ) : (
        <>
          <div className="driver-return" hidden={!showStart || area !== 'stations'}><button className="secondary-button" onClick={() => setShowStart(false)}><Icon name="chevronLeft" />Quay lại bản đồ và danh sách</button></div>
          <DriverCharging stationId={station?.id} stationName={station?.name} showSession={area === 'session'} showConnectors={area === 'stations' && showStart} onFindStations={showStations} onSessionStarted={sessionStarted} />
          {mapOpened && <div className="driver-map-container" hidden={area !== 'stations' || showStart}><DriverMapPage selectedStationId={station?.id} onOpenStation={selected => { setStation(selected); setShowStart(true) }} /></div>}
        </>
      )}
    </main>
  </div>
}
