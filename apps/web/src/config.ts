function basePath(value: string | undefined, fallback: string): string {
  return (value || fallback).replace(/\/$/, '')
}

export const config = {
  apiUrl: basePath(import.meta.env.VITE_API_URL, '/api'),
  tileUrl: basePath(import.meta.env.VITE_TILE_URL, '/tiles'),
} as const
