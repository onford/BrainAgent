import { t } from '../i18n'
import type { StreamActivity } from '../types/session'

export function agentLabel(name: string | null | undefined) {
  return ({ get orchestrator() { return t('Assistant') }, get data_survey() { return t('Data research') }, get data_preprocessing() { return t('Data preprocessing') }, get data_collection() { return t('Data ingestion') }, get data_evaluation() { return t('Performance evaluation') }, get data_report() { return t('Report generation') }, get data_delivery() { return t('Data delivery') } } as Record<string,string>)[name ?? 'orchestrator'] || name
}

export function activityLabel(activity: StreamActivity): string {
  const labels: Record<string, string> = {
    get run_started() { return t('Starting analysis') },
    get thought() { return t('Planning next step') },
    get agent_started() { return t('Calling agent') },
    get observation() { return t('Result received') },
    get run_completed() { return t('Response complete') },
    get run_failed() { return t('Run failed') },
  }
  return activity.agent_name
    ? `${agentLabel(activity.agent_name)} · ${labels[activity.event_type] ?? activity.event_type}`
    : labels[activity.event_type] ?? activity.event_type
}
