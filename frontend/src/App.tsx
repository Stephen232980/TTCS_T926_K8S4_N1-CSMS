import { useState } from 'react'
import { AppShell } from './app/AppShell'
import { StationListPage } from './features/stations/pages/StationListPage'
import './App.css'

function App() {
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
      <StationListPage notice={notice} onNotice={showPrototypeNotice} />
    </AppShell>
  )
}

export default App
