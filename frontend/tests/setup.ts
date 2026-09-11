import { beforeEach } from 'vitest'
import { setLocale } from '../src/i18n'

// Existing regression fixtures assert the Chinese interface. Locale-specific
// tests explicitly switch languages after this reset.
beforeEach(() => setLocale('zh'))
