import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Icon } from '../../components/icons/Icon'
import type { MapStation } from '../../components/maps/StationMap'
import type { AuthenticatedUser } from '../auth/model/auth'
import { DriverAccountMenu } from './DriverAccountMenu'
import { DriverNotificationCenter } from './DriverNotificationCenter'
import { DriverPrivacy } from './DriverPrivacy'
import { DriverCharging } from './DriverCharging'
import { DriverMapPage } from './DriverMapPage'
import { DriverReservations } from '../reservations/DriverReservations'
import { DriverInvoicePage } from './DriverInvoicePage'
import { DriverWalletPage } from './DriverWalletPage'
import { WalletTopUpPage } from './WalletTopUpPage'
import { WalletTopUpReturn } from './WalletTopUpReturn'
import { createWalletTopUp, getWalletTopUp, refreshDriverWallet, type TopUpResult } from './walletTopUpApi'
import { readTopUpReturn } from './walletTopUpReturnUrl'
import './driver.css'

type Area = 'session' | 'stations' | 'wallet' | 'privacy' | 'reservations'
const hashArea = (): Area => {
  if (readTopUpReturn(window.location).isReturn) return 'wallet'
  if (window.location.hash.startsWith('#driver-invoice')) return 'wallet'
  if (window.location.hash === '#driver-reservations' || window.location.hash.startsWith('#driver-reservation-')) return 'reservations'
  if (window.location.hash === '#driver-privacy') return 'privacy'
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
  const mainRef = useRef<HTMLElement>(null)
  const [overlay, setOverlay] = useState<'notifications' | 'account' | null>(null)
  const [area, setArea] = useState<Area>(hashArea)
  const [invoiceView, setInvoiceView] = useState(() => window.location.hash.startsWith('#driver-invoice'))
  const [reservationFocus, setReservationFocus] = useState(() => /^#driver-reservation-([0-9a-f-]{36})$/i.exec(window.location.hash)?.[1])
  const [invoiceSessionId, setInvoiceSessionId] = useState<number | undefined>(() => {
    const match = /^#driver-invoice-(\d+)$/.exec(window.location.hash)
    return match ? Number(match[1]) : undefined
  })
  const openInvoice = useCallback((id?: number) => {
    setInvoiceView(true)
    setInvoiceSessionId(id)
    setArea('wallet')
    window.history.pushState(null, '', id === undefined ? '#driver-invoices' : `#driver-invoice-${id}`)
  }, [])
  const storageKey = `csms:topup:${currentUser.id}`
  const [trackedOrder, setTrackedOrder] = useState(() => readTopUpReturn(window.location).orderId || sessionStorage.getItem(storageKey) || '')
  useEffect(() => {
    const id = readTopUpReturn(window.location).orderId
    if (id) sessionStorage.setItem(storageKey, id)
  }, [storageKey])
  const [walletRevision, setWalletRevision] = useState(0)
  const [succeededOrder, setSucceededOrder] = useState(false)
  const [topUpExpanded, setTopUpExpanded] = useState(() => sessionStorage.getItem(storageKey) !== null || readTopUpReturn(window.location).isReturn)
  const rememberOrder = useCallback((id: string) => {
    sessionStorage.setItem(storageKey, id)
    setTrackedOrder(id)
    setSucceededOrder(false)
  }, [storageKey])
  const resolved = useCallback((result: TopUpResult) => {
    if (result.status === 'succeeded') setSucceededOrder(true)
    if (['succeeded', 'failed', 'cancelled'].includes(result.status)) {
      sessionStorage.removeItem(storageKey)
      setWalletRevision(value => value + 1)
    }
  }, [storageKey])
  const refreshWallet = useCallback(async () => {
    await refreshDriverWallet()
    setWalletRevision(value => value + 1)
  }, [])
  const [returnLocation, setReturnLocation] = useState(() => readTopUpReturn(window.location))
  const [manualOrderId, setManualOrderId] = useState('')
  const showingReturn = returnLocation.isReturn || Boolean(manualOrderId)
  const returnOrderId = manualOrderId || returnLocation.orderId || trackedOrder
  const [mapOpened, setMapOpened] = useState(() => hashArea() === 'stations')
  const [station, setStation] = useState<MapStation>()
  const [showStart, setShowStart] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState('')

  useEffect(() => {
    const change = () => {
      const next = hashArea()
      setOverlay(null)
      setArea(next)
      setReservationFocus(/^#driver-reservation-([0-9a-f-]{36})$/i.exec(window.location.hash)?.[1])
      setInvoiceView(window.location.hash.startsWith('#driver-invoice'))
      const invoiceMatch = /^#driver-invoice-(\d+)$/.exec(window.location.hash)
      setInvoiceSessionId(invoiceMatch ? Number(invoiceMatch[1]) : undefined)
      const returned = readTopUpReturn(window.location)
      setReturnLocation(returned)
      if (returned.orderId) rememberOrder(returned.orderId)
      setManualOrderId('')
      if (next === 'stations') setMapOpened(true)
      setShowStart(false)
    }
    window.addEventListener('hashchange', change)
    window.addEventListener('popstate', change)
    return () => { window.removeEventListener('hashchange', change); window.removeEventListener('popstate', change) }
  }, [rememberOrder])

  const navigate = useCallback((next: Area) => {
    setSucceededOrder(false)
    setArea(next)
    setOverlay(null)
    setReservationFocus(undefined)
    setInvoiceView(false)
    setReturnLocation({ isReturn: false, orderId: '' })
    setManualOrderId('')
    setShowStart(false)
    if (next === 'stations') setMapOpened(true)
    const safePath = window.location.pathname.replace(/\/(?:driver\/)?wallet\/topup\/return\/?$/i, '/')
    window.history.replaceState(null, '', `${safePath}#driver-${next}`)
  }, [])
  useEffect(() => {
    if (!succeededOrder) return
    const timer = window.setTimeout(() => {
      setTrackedOrder('')
      setSucceededOrder(false)
      navigate('wallet')
    }, 5000)
    return () => window.clearTimeout(timer)
  }, [succeededOrder, navigate])
  const showStations = useCallback(() => navigate('stations'), [navigate])
  const checkTopUpOrder = useCallback((orderId: string) => {
    rememberOrder(orderId)
    setArea('wallet')
    setManualOrderId(orderId)
    setReturnLocation({ isReturn: true, orderId })
    window.history.replaceState(null, '', `#driver-wallet-return?order_code=${encodeURIComponent(orderId)}`)
  }, [rememberOrder])
  const sessionStarted = useCallback(() => navigate('session'), [navigate])

  useLayoutEffect(() => {
    if (mainRef.current) mainRef.current.scrollTop = 0
    document.documentElement.scrollTop = 0
    document.body.scrollTop = 0
  }, [area, invoiceView, showStart, reservationFocus])

  async function logout() {
    setLoggingOut(true)
    setLogoutError('')
    try { await onLogout() }
    catch { setLogoutError('Chưa đăng xuất được. Hãy thử lại.') }
    finally { setLoggingOut(false) }
  }

  return <div className="driver-shell">
    <header className="driver-topbar" aria-label="CSMS">
      <a className="driver-brand" href="#driver-session" onClick={event => { event.preventDefault(); navigate('session') }}><Icon name="station" /><strong>CSMS</strong><span>Tài xế</span></a>
        <div className="driver-heading-tools">
          <DriverNotificationCenter key={currentUser.id} ownerId={currentUser.id} open={overlay === 'notifications'} onOpenChange={open => setOverlay(open ? 'notifications' : null)} />
          <DriverAccountMenu email={currentUser.email} open={overlay === 'account'} onOpenChange={open => setOverlay(open ? 'account' : null)} onNavigate={navigate} onLogout={() => void logout()} loggingOut={loggingOut} logoutError={logoutError} />
        </div>
    </header>
    <aside className="driver-sidebar">

      <nav className="driver-navigation" aria-label="Khu vực tài xế">
        {([
          { key: 'session', label: 'Phiên sạc của bạn', icon: 'session' },
          { key: 'stations', label: 'Tìm trạm', icon: 'station' },
          { key: 'wallet', label: 'Ví của bạn', icon: 'wallet' },
          { key: 'reservations', label: 'Lịch sử đặt chỗ', icon: 'session' },
        ] as const).map(item => <a className={item.key === 'reservations' ? 'driver-desktop-reservations' : undefined} key={item.key} href={`#driver-${item.key}`} aria-current={area === item.key ? 'page' : undefined} onClick={event => { event.preventDefault(); navigate(item.key) }}><Icon name={item.icon} /><span>{item.label}</span></a>)}
      </nav>
      {onExit && <footer className="driver-workspace-exit"><button type="button" onClick={onExit}>Đổi khu vực</button></footer>}
    </aside>
    <main ref={mainRef} className="driver-main">
      <header className="driver-heading">
        <div className="driver-heading-copy"><h1>
          {area === 'reservations' ? reservationFocus ? 'Chi tiết đặt chỗ' : 'Lịch sử đặt chỗ' : area === 'privacy' ? 'Dữ liệu cá nhân' : area === 'session'
            ? reservationFocus ? 'Chi tiết đặt chỗ' : 'Phiên sạc của bạn'
            : area === 'wallet'
              ? invoiceView ? 'Hóa đơn của bạn' : showingReturn ? 'Trạng thái nạp tiền' : 'Ví tiền của bạn'
              : showStart
                ? 'Bắt đầu sạc'
                : 'Tìm trạm sạc'}
        </h1>
        <p>
          {area === 'reservations' ? 'Xem trạng thái, thời gian giữ chỗ và phí đã xác nhận.' : area === 'privacy' ? 'Yêu cầu ẩn danh tài khoản và theo dõi kết quả xử lý.' : area === 'session'
            ? reservationFocus ? 'Mức phí đã xác nhận và kết quả xử lý đặt chỗ.' : 'Theo dõi điện năng và thời gian từ trụ đang sạc.'
            : area === 'wallet'
              ? invoiceView
                ? 'Xem chi tiết tiền điện và phí chiếm trụ của từng phiên.'
                : showingReturn
                ? 'Theo dõi trạng thái giao dịch nạp tiền của bạn.'
                : 'Theo dõi số dư, lịch sử giao dịch và nạp tiền vào ví.'
              : showStart
                ? 'Chọn đúng đầu nối, cắm súng vào xe rồi gửi yêu cầu.'
                : 'Xem vị trí trạm và tìm nơi sạc phù hợp.'}
        </p></div>

      </header>
      {area === 'wallet' && invoiceView && <div className="driver-wallet-stack">
        <button className="navigation-link secondary-button driver-wallet-back" onClick={() => { setInvoiceView(false); window.history.pushState(null, '', '#driver-wallet') }}><Icon name="chevronLeft" />Quay lại ví</button>
        <DriverInvoicePage sessionId={invoiceSessionId} onOpen={openInvoice} onBack={() => openInvoice()} />
      </div>}
      <div hidden={area !== 'wallet' || invoiceView}>
        {(showingReturn || trackedOrder) && <WalletTopUpReturn
          transactionId={returnOrderId}
          getStatus={getWalletTopUp}
          onResolved={resolved}
          onSucceeded={refreshWallet}
          onBack={showingReturn ? () => navigate('wallet') : undefined}
        />}
        {area === 'wallet' && !showingReturn && <div className="driver-wallet-stack">
          <DriverWalletPage key={`wallet-${walletRevision}`} onTopUp={() => {
            setTopUpExpanded(true)
            window.setTimeout(() => document.getElementById('topup-amount')?.focus(), 0)
          }} onOpenInvoice={openInvoice} topUpContent={<details className="driver-topup-disclosure" open={topUpExpanded} onToggle={event => setTopUpExpanded(event.currentTarget.open)}>
            <summary><Icon name="chevronRight" /><span>Nạp tiền</span></summary>
            <WalletTopUpPage key={`topup-${walletRevision}`} storageKey={storageKey} onOrder={rememberOrder}
              onTopUp={createWalletTopUp} onCheckOrder={checkTopUpOrder} onRedirect={navigateToPayment} />
          </details>} />
          <button className="secondary-button" onClick={() => openInvoice()}>Xem hóa đơn phiên sạc</button>
        </div>}
      </div>
      {area === 'reservations' && <DriverReservations key={reservationFocus ?? 'history'} ownerId={currentUser.id} focusedId={reservationFocus} standalone />}
      {area === 'privacy' && <DriverPrivacy />}
      {(area === 'session' || area === 'stations') && (
        <>
          <div className="driver-return" hidden={!showStart || area !== 'stations'}><button className="navigation-link secondary-button" onClick={() => setShowStart(false)}><Icon name="chevronLeft" />Quay lại bản đồ và danh sách</button></div>
          <DriverCharging ownerId={currentUser.id} stationId={station?.id} stationName={station?.name} showSession={area === 'session'} showConnectors={area === 'stations' && showStart} onFindStations={showStations} onSessionStarted={sessionStarted} />
          {mapOpened && <div className="driver-map-container" hidden={area !== 'stations' || showStart}><DriverMapPage selectedStationId={station?.id} onOpenStation={selected => { setStation(selected); setShowStart(true) }} /></div>}
        </>
      )}
    </main>
  </div>
}
