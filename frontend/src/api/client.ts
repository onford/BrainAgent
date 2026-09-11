import { t } from '../i18n'
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
export const apiUrl = (path: string): string => `${API_BASE}${path}`

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body.detail ?? t('Request failed'))
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
