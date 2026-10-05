import { useEffect, useState } from 'react'

export function useResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [version, setVersion] = useState(0)
  const [state, setState] = useState<{
    load: typeof load
    version: number
    data?: T
    error?: unknown
  }>()
  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ load, version, data })
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ load, version, error })
      })
    return () => controller.abort()
  }, [load, version])
  const current = state?.load === load && state.version === version
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : undefined,
    loading: !current,
    reload: () => setVersion((v) => v + 1),
  }
}
