import type { AgentResult, ExecutionEvent } from '../types/agent'

export function stringifyValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function activityDetail(
  event: Pick<ExecutionEvent, 'event_type' | 'data'>,
): string | undefined {
  if (event.event_type !== 'observation') return undefined
  const result = event.data.result as AgentResult | undefined
  if (!result || result.output === null || result.output === undefined) return undefined
  const detail = stringifyValue(result.output)
  return detail.length > 1800 ? `${detail.slice(0, 1800)}\n…` : detail
}
