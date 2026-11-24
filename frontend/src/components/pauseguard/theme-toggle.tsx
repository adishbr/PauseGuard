import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  THEME_CHANGE_EVENT,
  applyTheme,
  getStoredTheme,
  setTheme,
  type ThemeMode,
} from "@/lib/theme";

const OPTIONS: { mode: ThemeMode; label: string; Icon: typeof Moon }[] = [
  { mode: "dark", label: "Dark", Icon: Moon },
  { mode: "light", label: "Light", Icon: Sun },
  { mode: "system", label: "System", Icon: Monitor },
];

export function ThemeToggle({ className }: { className?: string }) {
  // SSR renders "system"; the real preference is read after hydration.
  const [mode, setMode] = useState<ThemeMode>("system");

  useEffect(() => {
    setMode(getStoredTheme());
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent<{ mode: ThemeMode }>).detail;
      setMode(detail?.mode ?? getStoredTheme());
    };
    window.addEventListener(THEME_CHANGE_EVENT, onChange);

    const media =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-color-scheme: light)")
        : null;
    const onSystem = () => {
      if (getStoredTheme() === "system") applyTheme("system");
    };
    media?.addEventListener?.("change", onSystem);
    return () => {
      window.removeEventListener(THEME_CHANGE_EVENT, onChange);
      media?.removeEventListener?.("change", onSystem);
    };
  }, []);

  return (
    <div
      role="group"
      aria-label="Color theme"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full border border-hairline bg-glass p-0.5 backdrop-blur-md",
        className,
      )}
    >
      {OPTIONS.map(({ mode: option, label, Icon }) => {
        const active = mode === option;
        return (
          <button
            key={option}
            type="button"
            aria-pressed={active}
            aria-label={`${label} theme`}
            title={`${label} theme`}
            onClick={() => {
              setTheme(option);
              setMode(option);
            }}
            className={cn(
              "grid size-8 place-items-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:rounded-full",
              active && "bg-foreground/10 text-foreground shadow-[inset_0_0_0_1px_var(--glass-edge)]",
            )}
          >
            <Icon className="size-3.5" aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}
