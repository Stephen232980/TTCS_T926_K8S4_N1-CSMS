import { useState } from 'react'
import { AppShell } from './app/AppShell'
import type { ChargePointApi } from './features/chargePoints/api/chargePointApi'
import type { StationApi } from './features/stations/api/stationApi'
import { StationDetailPage } from './features/stations/pages/StationDetailPage'
import { StationListPage } from './features/stations/pages/StationListPage'
import './App.css'

interface AppProps {
  stationApi?: StationApi
  chargePointApi?: ChargePointApi
}

function App({ stationApi, chargePointApi }: AppProps) {
  const [notice, setNotice] = useState('')
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null)

  const showPrototypeNotice = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(''), 3200)
  }

  return (
    <AppShell
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
