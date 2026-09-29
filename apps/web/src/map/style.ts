import type { StyleSpecification } from 'maplibre-gl'
import { config } from '../config'

export const demoSourceId = 'demo-sites'
export const railwaySourceId = 'railway-segments'

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
    [railwaySourceId]: {
      type: 'vector',
      tiles: [`${config.tileUrl}/railway_segments/{z}/{x}/{y}`],
      minzoom: 5,
      maxzoom: 14,
      attribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>',
    },
  },
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#e8edf0' },
    },
    {
      id: 'railway-main',
      type: 'line',
      source: railwaySourceId,
      'source-layer': 'railway_segments',
      minzoom: 5,
      maxzoom: 15,
      filter: ['!', ['has', 'service']],
      paint: {
        'line-color': '#5b626a',
        'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.7, 10, 1.4, 14, 2.2],
        'line-opacity': 0.8,
      },
    },
    {
      id: 'railway-service',
      type: 'line',
      source: railwaySourceId,
      'source-layer': 'railway_segments',
      minzoom: 11,
      maxzoom: 15,
      filter: ['has', 'service'],
      paint: {
        'line-color': '#8d969d',
        'line-width': 0.9,
        'line-opacity': 0.65,
      },
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
