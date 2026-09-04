import { apiRequest } from './client'
import type { Session } from '../types/session'
import { activityDetail } from '../utils/activity'

function hydrateSession(session: Session): Session {
  session.messages.forEach((message) => {
    message.activities = message.activities?.map((activity) => ({
      ...activity,
      detail: activity.detail ?? activityDetail({
        event_type: activity.event_type,
        data: activity.data ?? {},
      }),
    }))
  })
  return session
}

export function createSession(): Promise<Session> {
  return apiRequest<Session>('/api/sessions', { method: 'POST' }).then(hydrateSession)
}

export function fetchSessions(): Promise<Session[]> {
  return apiRequest<Session[]>('/api/sessions').then((sessions) => sessions.map(hydrateSession))
}

export function fetchSession(sessionId: string): Promise<Session> {
  return apiRequest<Session>(`/api/sessions/${sessionId}`).then(hydrateSession)
}
