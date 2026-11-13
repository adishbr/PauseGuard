export type ThemeMode = 'dark' | 'light' | 'system'
export type EffectiveTheme = 'dark' | 'light'

const THEME_STORAGE_KEY = 'pauseguard:theme'
export const THEME_CHANGE_EVENT = 'pauseguard:theme-change'

export function getSystemTheme(): EffectiveTheme {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function getStoredTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'system'
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY)
    if (saved === 'dark' || saved === 'light' || saved === 'system') return saved
  } catch {
    // Storage access restricted (private mode / sandboxed)
  }
  return 'system'
}

export function getEffectiveTheme(preference: ThemeMode = getStoredTheme()): EffectiveTheme {
  if (preference === 'system') return getSystemTheme()
  return preference
}

export function applyTheme(mode: ThemeMode): EffectiveTheme {
  const effective = getEffectiveTheme(mode)
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', effective)
    document.documentElement.setAttribute('data-theme-preference', mode)
    document.documentElement.style.colorScheme = effective
  }
  return effective
}

export function setTheme(mode: ThemeMode): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    // Ignore storage write failures
  }
  const effective = applyTheme(mode)
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: { mode, effective } }))
  }
}

export function initTheme(): () => void {
  const current = getStoredTheme()
  applyTheme(current)

  if (typeof window === 'undefined') return () => {}

  const media = window.matchMedia('(prefers-color-scheme: light)')
  function handleSystemChange() {
    if (getStoredTheme() === 'system') {
      const effective = applyTheme('system')
      window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: { mode: 'system', effective } }))
    }
  }

  media.addEventListener('change', handleSystemChange)
  return () => media.removeEventListener('change', handleSystemChange)
}

