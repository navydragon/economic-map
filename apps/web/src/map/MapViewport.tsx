import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { demoSourceId, style } from './style'

type TileStatus = 'loading' | 'ready' | 'error'

interface MapViewportProps {
  onTileStatusChange: (status: TileStatus) => void
}

export function MapViewport({ onTileStatusChange }: MapViewportProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [mapError, setMapError] = useState<string | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    let map: maplibregl.Map
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style,
        center: [92, 61],
        zoom: 2.1,
        minZoom: 1,
        maxZoom: 15,
        attributionControl: false,
      })
    } catch (error) {
      setMapError(error instanceof Error ? error.message : 'Map could not initialize')
      onTileStatusChange('error')
      return
    }

    let tileFailed = false
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.addControl(new maplibregl.AttributionControl({ compact: false }), 'bottom-right')
    map.on('sourcedata', (event) => {
      if (!tileFailed && event.sourceId === demoSourceId && map.isSourceLoaded(demoSourceId)) {
        onTileStatusChange('ready')
      }
    })
    map.on('error', () => {
      tileFailed = true
      onTileStatusChange('error')
    })

    return () => map.remove()
  }, [onTileStatusChange])

  return (
    <>
      <div ref={containerRef} className="map" aria-label="Map of synthetic demo sites and transport infrastructure" />
      {mapError && <div className="map-error" role="alert">Map error: {mapError}</div>}
    </>
  )
}
