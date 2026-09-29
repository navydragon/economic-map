import { useEffect, useState } from 'react'
import { config } from './config'
import { MapViewport } from './map/MapViewport'

type Status = 'loading' | 'ready' | 'error'

export function App() {
  const [tileStatus, setTileStatus] = useState<Status>('loading')
  const [apiStatus, setApiStatus] = useState<Status>('loading')
  const [databaseStatus, setDatabaseStatus] = useState<Status>('loading')

  useEffect(() => {
    const controller = new AbortController()

    fetch(`${config.apiUrl}/health`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('API health request failed')
        setApiStatus('ready')
      })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name !== 'AbortError') setApiStatus('error')
      })

    fetch(`${config.apiUrl}/health/db`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Database health request failed')
        setDatabaseStatus('ready')
      })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name !== 'AbortError') setDatabaseStatus('error')
      })

    return () => controller.abort()
  }, [])

  return (
    <main>
      <MapViewport onTileStatusChange={setTileStatus} />
      <section className="status-panel" aria-label="Development status">
        <h1>Russia Map</h1>
        <p>Phase 1 · synthetic development data</p>
        <dl>
          <div><dt>Vector tiles</dt><dd className={tileStatus}>{tileStatus}</dd></div>
          <div><dt>API</dt><dd className={apiStatus}>{apiStatus}</dd></div>
          <div><dt>PostGIS via API</dt><dd className={databaseStatus}>{databaseStatus}</dd></div>
        </dl>
        {tileStatus === 'error' && <p role="alert">Demo tiles could not load. Check Martin and PostGIS.</p>}
        {apiStatus === 'error' && <p role="alert">API could not load. Check the FastAPI server.</p>}
        {databaseStatus === 'error' && <p role="alert">Database check failed. Check PostGIS.</p>}
        <p className="legend"><span aria-hidden="true" /> Synthetic demo sites</p>
      </section>
    </main>
  )
}
