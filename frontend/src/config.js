/**
 * Central application configuration.
 * - In local development: defaults to 'http://localhost:8000'
 * - In staging/production: uses VITE_API_BASE from environment, or falls back to '' (relative path)
 */
export const API_BASE = (
  import.meta.env.VITE_API_BASE ??
  (import.meta.env.DEV ? 'http://localhost:8000' : '')
).replace(/\/$/, '')

