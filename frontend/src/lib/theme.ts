// Mirrors PauseGuard's theme service contract (storage key + change event) so the
// preview can be dropped into the main app without migrating saved preferences.
export type ThemeMode = "dark" | "light" | "system";
export type EffectiveTheme = "dark" | "light";

export const THEME_STORAGE_KEY = "pauseguard:theme";
export const THEME_CHANGE_EVENT = "pauseguard:theme-change";

export function getSystemTheme(): EffectiveTheme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function getStoredTheme(): ThemeMode {
  if (typeof window === "undefined") return "system";
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "dark" || saved === "light" || saved === "system") return saved;
  } catch {
    // storage unavailable
  }
  return "system";
}

export function resolveTheme(mode: ThemeMode): EffectiveTheme {
  return mode === "system" ? getSystemTheme() : mode;
}

export function applyTheme(mode: ThemeMode): EffectiveTheme {
  const effective = resolveTheme(mode);
  if (typeof document !== "undefined") {
    const root = document.documentElement;
    root.setAttribute("data-theme", effective);
    root.setAttribute("data-theme-preference", mode);
    root.style.colorScheme = effective;
  }
  return effective;
}

export function setTheme(mode: ThemeMode): EffectiveTheme {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    // ignore
  }
  const effective = applyTheme(mode);
  window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: { mode, effective } }));
  return effective;
}

/** Inline, pre-paint script: applies the saved theme before React hydrates. */
export const themeBootScript = `(function(){try{var k='${THEME_STORAGE_KEY}';var m=localStorage.getItem(k);if(m!=='light'&&m!=='dark')m='system';var e=m==='system'?(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'):m;var d=document.documentElement;d.setAttribute('data-theme',e);d.setAttribute('data-theme-preference',m);d.style.colorScheme=e;}catch(_){}})();`;
