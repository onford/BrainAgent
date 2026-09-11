import { t } from './index'
import type { MessageKey } from './en'

const stages: Record<string, MessageKey> = {
  data_survey: 'Data research',
  data_collection: 'Data ingestion',
  data_preprocessing: 'Data preprocessing',
  data_evaluation: 'Result selection',
  data_report: 'Reporting',
  data_delivery: 'Data delivery',
}

/** Known module IDs have maintained labels; unknown extensions keep their own name. */
export function stageLabel(name: string, fallback = name): string {
  return stages[name] ? t(stages[name]) : fallback
}
