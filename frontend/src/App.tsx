import { useState } from 'react'
import { AppShell } from './app/AppShell'
import type { StationApi } from './features/stations/api/stationApi'
import { StationListPage } from './features/stations/pages/StationListPage'
import './App.css'

interface AppProps {
  stationApi?: StationApi
}

function App({ stationApi }: AppProps) {
  const [notice, setNotice] = useState('')

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
      <StationListPage
        notice={notice}
        onNotice={showPrototypeNotice}
        api={stationApi}
      />
    </AppShell>
  )
}

export default App
