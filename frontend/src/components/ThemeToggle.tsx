import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icon.tsx'
import {
  getStoredTheme,
  getEffectiveTheme,
  setTheme,
  THEME_CHANGE_EVENT,
  type ThemeMode,
  type EffectiveTheme,
} from '../services/theme.ts'

const options: { mode: ThemeMode; label: string; icon: 'moon' | 'sun' | 'monitor' }[] = [
  { mode: 'dark', label: 'Dark', icon: 'moon' },
  { mode: 'light', label: 'Light', icon: 'sun' },
  { mode: 'system', label: 'System', icon: 'monitor' },
]

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [preference, setPreference] = useState<ThemeMode>(() => getStoredTheme())
  const [effective, setEffective] = useState<EffectiveTheme>(() => getEffectiveTheme())
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onThemeChange(e: Event) {
      const detail = (e as CustomEvent<{ mode: ThemeMode; effective: EffectiveTheme }>).detail
      if (detail) {
        setPreference(detail.mode)
        setEffective(detail.effective)
      } else {
        setPreference(getStoredTheme())
        setEffective(getEffectiveTheme())
      }
    }

    window.addEventListener(THEME_CHANGE_EVENT, onThemeChange)
    return () => window.removeEventListener(THEME_CHANGE_EVENT, onThemeChange)
  }, [])

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('click', onDocClick)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('click', onDocClick)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  function selectMode(next: ThemeMode) {
    setTheme(next)
    setPreference(next)
    setEffective(getEffectiveTheme(next))
    setOpen(false)
  }

  const currentIcon = preference === 'system' ? 'monitor' : effective === 'light' ? 'sun' : 'moon'
  const currentLabel = options.find((o) => o.mode === preference)?.label ?? 'Theme'

  return (
    <div className={`theme-toggle-container ${compact ? 'compact' : ''}`} ref={menuRef}>
      <button
        type="button"
        className="theme-toggle-btn"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={`Current theme: ${currentLabel}. Click to choose Light, Dark, or System theme.`}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={`Theme: ${currentLabel}`}
      >
        <span className="theme-toggle-icon">
          <Icon name={currentIcon} size={16} />
        </span>
        {!compact && <span className="theme-toggle-label">{currentLabel}</span>}
        <span className="theme-toggle-arrow" aria-hidden="true">▾</span>
      </button>

      {open && (
        <div className="theme-toggle-dropdown" role="listbox" aria-label="Select color theme">
          {options.map((opt) => {
            const isSelected = preference === opt.mode
            return (
              <button
                key={opt.mode}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={`theme-option-btn ${isSelected ? 'selected' : ''}`}
                onClick={() => selectMode(opt.mode)}
              >
                <Icon name={opt.icon} size={15} />
                <span>{opt.label}</span>
                {isSelected && <span className="theme-selected-mark"><Icon name="check" size={14} /></span>}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

