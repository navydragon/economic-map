import type { StyleSpecification } from 'maplibre-gl'
import { config } from '../config'

export const demoSourceId = 'demo-sites'
export const railwaySourceId = 'railway-segments'
export const roadSourceId = 'road-segments'
export const portSourceId = 'ports'

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
    [roadSourceId]: {
      type: 'vector',
      tiles: [`${config.tileUrl}/road_segments/{z}/{x}/{y}`],
      minzoom: 5,
      maxzoom: 14,
      attribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>',
    },
    [portSourceId]: {
      type: 'vector',
      tiles: [`${config.tileUrl}/ports/{z}/{x}/{y}`],
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
      id: 'road-main',
      type: 'line',
      source: roadSourceId,
      'source-layer': 'road_segments',
      minzoom: 5,
      maxzoom: 15,
      filter: ['==', ['get', 'is_link'], false],
      paint: {
        'line-color': ['match', ['get', 'road_class'],
          'motorway', '#ad8260', 'trunk', '#ae8d6d', 'primary', '#a49780',
          'secondary', '#a6a39a', 'tertiary', '#b0b0ab', '#b0b0ab'],
        'line-width': ['interpolate', ['linear'], ['zoom'],
          5, ['match', ['get', 'road_class'], 'motorway', 1.3, 'trunk', 1.1, 0.75],
          14, ['match', ['get', 'road_class'], 'motorway', 3.2, 'trunk', 2.8,
            'primary', 2.3, 'secondary', 1.8, 1.4]],
        'line-opacity': 0.62,
      },
    },
    {
      id: 'road-link',
      type: 'line',
      source: roadSourceId,
      'source-layer': 'road_segments',
      minzoom: 10,
      maxzoom: 15,
      filter: ['==', ['get', 'is_link'], true],
      paint: {
        'line-color': '#ad9988',
        'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.8, 14, 1.5],
        'line-opacity': 0.55,
      },
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
      id: 'port-markers',
      type: 'circle',
      source: portSourceId,
      'source-layer': 'ports',
      minzoom: 5,
      maxzoom: 15,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 3.5, 10, 5.5],
        'circle-color': ['match', ['get', 'facility_class'],
          'cargo_terminal', '#176b75', 'commercial_port', '#267783',
          'fishing_port', '#4c8b91', '#608e96'],
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 1.4,
      },
    },
    {
      id: 'port-labels',
      type: 'symbol',
      source: portSourceId,
      'source-layer': 'ports',
      minzoom: 6,
      maxzoom: 15,
      filter: ['has', 'name'],
      layout: {
        'text-field': ['get', 'name'],
        'text-size': 11,
        'text-offset': [0, 1.2],
        'text-anchor': 'top',
      },
      paint: {
        'text-color': '#23545f',
        'text-halo-color': '#ffffff',
        'text-halo-width': 1.3,
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
