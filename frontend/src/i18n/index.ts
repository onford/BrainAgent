import { computed, readonly, ref } from 'vue'
import type { MessageKey } from './en'
import { zh } from './zh'

export type Locale = 'en' | 'zh'
export const localeStorageKey = 'brainagent.locale'

export function readLocale(): Locale {
  try { return localStorage.getItem(localeStorageKey) === 'zh' ? 'zh' : 'en' }
  catch { return 'en' }
}

const currentLocale = ref<Locale>(readLocale())
export const locale = readonly(currentLocale)
export const formatLocale = computed(() => currentLocale.value === 'zh' ? 'zh-CN' : 'en-US')

export function setLocale(value: string): void {
  if (value !== 'en' && value !== 'zh') return
  currentLocale.value = value
  if (typeof document !== 'undefined') document.documentElement.lang = value === 'zh' ? 'zh-CN' : 'en'
  try { localStorage.setItem(localeStorageKey, value) } catch { /* In-memory switching remains available. */ }
}

/** Translate application messages only. Never pass stored report text or user content. */
export function t(key: MessageKey, values: Record<string | number, unknown> = {}): string {
  const message = currentLocale.value === 'zh' ? zh[key] ?? key : key
  return message.replace(/\{(\w+)\}/g, (token, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name] ?? '—') : token,
  )
}

export function initializeLocale(): void {
  setLocale(readLocale())
}
