import { apiRequest, apiUrl } from './client'
import type { SearchRequest, SearchState, SearchSummary } from '../types/search'

const searchPath = (id: string) => `/api/searches/${encodeURIComponent(id)}`

export const fetchSearches = () => apiRequest<SearchSummary[]>('/api/searches')
export const fetchSearch = (id: string, includeArtifacts = true) => apiRequest<SearchState>(`${searchPath(id)}?include_artifacts=${includeArtifacts}`)
export const createSearch = (request: SearchRequest) => apiRequest<SearchState>('/api/searches', {
  method: 'POST', body: JSON.stringify(request),
})
export const retrySearch = (id: string) => apiRequest<SearchState>(`${searchPath(id)}/retry`, { method: 'POST' })
export const cancelSearch = (id: string) => apiRequest<SearchState>(`${searchPath(id)}/cancel`, { method: 'POST' })

export function searchArtifactUrl(id: string, artifact: { name: string; url?: string }, download = true): string {
  const path = artifact.url || `${searchPath(id)}/artifacts/${artifact.name.split('/').map(encodeURIComponent).join('/')}`
  const [withoutHash, hash] = path.split('#', 2)
  const [base, query] = withoutHash.split('?', 2)
  // Only HTTP(S) or API-relative links are usable artifact locations.
  if (!/^https?:\/\//i.test(base) && !base.startsWith('/api/')) return ''
  const params = new URLSearchParams(query)
  params.set('download', String(download))
  return `${/^https?:\/\//i.test(base) ? base : apiUrl(base)}?${params}${hash ? `#${hash}` : ''}`
}
