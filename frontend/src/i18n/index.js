import { createI18n } from 'vue-i18n'
import { nextTick } from 'vue'
import en from './locales/en.json'
import pl from './locales/pl.json'
import uk from './locales/uk.json'

export const SUPPORTED_LOCALES = {
  en: { name: 'English', flag: '\u{1F1EC}\u{1F1E7}' },
  uk: { name: 'Українська', flag: '\u{1F1FA}\u{1F1E6}' },
  pl: { name: 'Polski', flag: '\u{1F1F5}\u{1F1F1}' }
}

export const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem('locale') || 'en',
  fallbackLocale: 'en',
  messages: { en, uk, pl }
})

/**
 * Dynamically load a locale from the API or static imports.
 * Registers the locale in vue-i18n at runtime so it can be used immediately.
 */
export async function loadLocaleMessages(locale) {
  // Already loaded
  if (i18n.global.availableLocales.includes(locale)) {
    return setI18nLanguage(locale)
  }

  // Try fetching from API first (works for any language added via admin panel)
  try {
    const { default: client } = await import('@/api/client')
    const { data } = await client.get(`/translations/${locale}`)
    i18n.global.setLocaleMessage(locale, data)
    return setI18nLanguage(locale)
  } catch {
    // Fallback: try dynamic import of local JSON file
    try {
      const messages = await import(`./locales/${locale}.json`)
      i18n.global.setLocaleMessage(locale, messages.default || messages)
      return setI18nLanguage(locale)
    } catch {
      console.warn(`[i18n] Could not load locale: ${locale}`)
      return false
    }
  }
}

export function setI18nLanguage(locale) {
  i18n.global.locale.value = locale
  localStorage.setItem('locale', locale)
  document.querySelector('html')?.setAttribute('lang', locale)
  return nextTick()
}

/**
 * Fetch the list of available languages from the API and
 * update the SUPPORTED_LOCALES registry.
 */
export async function fetchAvailableLocales() {
  try {
    const { default: client } = await import('@/api/client')
    const { data } = await client.get('/translations/languages')
    for (const lang of data) {
      if (!SUPPORTED_LOCALES[lang.code]) {
        SUPPORTED_LOCALES[lang.code] = { name: lang.name, flag: lang.flag }
      }
    }
    return data
  } catch {
    return Object.entries(SUPPORTED_LOCALES).map(([code, meta]) => ({
      code,
      ...meta,
      translated: 0,
      total: 0,
      percentage: code === 'en' ? 100 : 0
    }))
  }
}
