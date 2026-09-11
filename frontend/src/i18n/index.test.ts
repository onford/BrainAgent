import { afterEach, describe, expect, it, vi } from 'vitest'
import { en } from './en'
import { zh } from './zh'
import { formatLocale, locale, localeStorageKey, readLocale, setLocale, t } from './index'

afterEach(() => vi.restoreAllMocks())

describe('English-source localization', () => {
  it('maintains a complete Chinese catalog with identical placeholders', () => {
    expect(new Set(en).size).toBe(en.length)
    expect(Object.keys(zh).sort()).toEqual([...en].sort())
    const tokens = (s: string) => [...s.matchAll(/\{\w+\}/g)].map(m => m[0]).sort()
    for (const key of en) {
      expect(zh[key].trim(), key).not.toBe('')
      expect(tokens(zh[key]), key).toEqual(tokens(key))
    }
  })

  it('defaults to English, persists the choice, and rejects unsupported values', () => {
    localStorage.removeItem(localeStorageKey)
    expect(readLocale()).toBe('en')
    setLocale('en')
    expect(document.documentElement.lang).toBe('en')
    expect(formatLocale.value).toBe('en-US')
    setLocale('zh')
    expect(readLocale()).toBe('zh')
    expect(document.documentElement.lang).toBe('zh-CN')
    setLocale('de')
    expect(locale.value).toBe('zh')
    localStorage.setItem(localeStorageKey, 'invalid')
    expect(readLocale()).toBe('en')
  })

  it('switches without storage access and interpolates values literally', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Blocked') })
    expect(readLocale()).toBe('en')
    setLocale('en')
    expect(t('Open {0} →', { 0: '<script>$&{1}</script>' })).toBe('Open <script>$&{1}</script> →')
    expect(t('Scope: {0} development subjects · {1} eligible trials · {2} outer folds.', { 0: 109, 1: 4918, 2: 5 }))
      .toBe('Scope: 109 development subjects · 4918 eligible trials · 5 outer folds.')
    setLocale('zh')
    expect(t('Signal quality')).toBe('信号质量')
  })
})
