import type { StyleSpecification } from 'maplibre-gl'
import { config } from '../config'

export const demoSourceId = 'demo-sites'

export const style: StyleSpecification = {
  version: 8,
  name: 'Neutral development map',
  sources: {
    [demoSourceId]: {
      type: 'vector',
      tiles: [`${config.tileUrl}/demo_sites/{z}/{x}/{y}`],
      minzoom: 0,
      maxzoom: 14,
    },
  },
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#e8edf0' },
    },
    {
      id: 'demo-sites-halo',
      type: 'circle',
      source: demoSourceId,
      'source-layer': 'demo_sites',
      minzoom: 1,
      maxzoom: 15,
      paint: {
        'circle-radius': 11,
        'circle-color': '#ffffff',
        'circle-opacity': 0.85,
      },
    },
    {
      id: 'demo-sites-points',
      type: 'circle',
      source: demoSourceId,
      'source-layer': 'demo_sites',
      minzoom: 1,
      maxzoom: 15,
      paint: {
        'circle-radius': 6,
        'circle-color': '#176b75',
        'circle-stroke-color': '#12434b',
        'circle-stroke-width': 1,
      },
    },
  ],
}
