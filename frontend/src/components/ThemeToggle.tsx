import { useEffect, useState } from "react";
import { Icon } from "./Icon.tsx";
import {
  getStoredTheme,
  getEffectiveTheme,
  setTheme,
  THEME_CHANGE_EVENT,
  type ThemeMode,
  type EffectiveTheme,
} from "../services/theme.ts";

const options: { mode: ThemeMode; label: string; icon: "moon" | "sun" | "monitor" }[] = [
  { mode: "dark", label: "Dark", icon: "moon" },
  { mode: "light", label: "Light", icon: "sun" },
  { mode: "system", label: "System", icon: "monitor" },
];

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [preference, setPreference] = useState<ThemeMode>(() => getStoredTheme());
  const [, setEffective] = useState<EffectiveTheme>(() => getEffectiveTheme());

  useEffect(() => {
    function onThemeChange(e: Event) {
      const detail = (e as CustomEvent<{ mode: ThemeMode; effective: EffectiveTheme }>).detail;
      if (detail) {
        setPreference(detail.mode);
        setEffective(detail.effective);
      } else {
        setPreference(getStoredTheme());
        setEffective(getEffectiveTheme());
      }
    }

    window.addEventListener(THEME_CHANGE_EVENT, onThemeChange);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, onThemeChange);
  }, []);

  function selectMode(next: ThemeMode) {
    setTheme(next);
    setPreference(next);
    setEffective(getEffectiveTheme(next));
  }

  return (
    <div
      role="group"
      aria-label="Color theme"
      className={`pg-theme-pill${compact ? " is-compact" : ""}`}
    >
      {options.map((opt) => {
        const active = preference === opt.mode;
        return (
          <button
            key={opt.mode}
            type="button"
            aria-pressed={active}
            aria-label={`${opt.label} theme`}
            title={`${opt.label} theme`}
            className={`pg-theme-pill-btn${active ? " is-active" : ""}`}
            onClick={() => selectMode(opt.mode)}
          >
            <Icon name={opt.icon} size={14} />
          </button>
        );
      })}
    </div>
  );
}
