import { useEffect, useState } from "react";
import { ArrowRight, Menu, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Wordmark } from "./brand-mark";
import { ThemeToggle } from "./theme-toggle";
import { DESTINATIONS } from "./destinations";

const NAV = [
  { href: DESTINATIONS.howItWorks, label: "How it works" },
  { href: DESTINATIONS.privacy, label: "Privacy" },
  { href: DESTINATIONS.guardian, label: "Guardian portal" },
] as const;

const navLink =
  "rounded-md text-sm text-muted-foreground transition-colors hover:text-foreground";

export function SiteHeader() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header className="sticky top-0 z-40">
      <div className="absolute inset-0 border-b border-hairline bg-background/55 backdrop-blur-xl" />
      <div className="relative mx-auto flex h-16 max-w-[90rem] items-center justify-between gap-4 px-5 sm:px-8 lg:h-20 lg:px-12">
        <a href={DESTINATIONS.home} aria-label="PauseGuard home" className="rounded-md">
          <Wordmark />
        </a>

        <nav aria-label="Main navigation" className="hidden md:block">
          <ul className="flex items-center gap-8">
            {NAV.map((item) => (
              <li key={item.href}>
                <a href={item.href} className={navLink}>
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex items-center gap-2 sm:gap-3">
          <ThemeToggle className="hidden sm:inline-flex" />
          <a href={DESTINATIONS.login} className={`${navLink} hidden px-2 py-1 sm:inline-flex`}>
            Log in
          </a>
          <Button asChild variant="glow" size="sm" className="hidden h-9 px-4 sm:inline-flex">
            <a href={DESTINATIONS.signup}>
              Get started <ArrowRight aria-hidden="true" />
            </a>
          </Button>
          <button
            type="button"
            className="grid size-10 place-items-center rounded-full border border-hairline bg-glass text-foreground md:hidden"
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={open ? "Close menu" : "Open menu"}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X className="size-4" aria-hidden="true" /> : <Menu className="size-4" aria-hidden="true" />}
          </button>
        </div>
      </div>

      {open && (
        <div id="mobile-menu" className="relative border-b border-hairline bg-background/95 backdrop-blur-xl md:hidden">
          <nav aria-label="Mobile navigation" className="mx-auto max-w-[90rem] px-5 pb-6 pt-2 sm:px-8">
            <ul className="divide-y divide-[var(--hairline)]">
              {NAV.map((item) => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className="block rounded-md py-3.5 font-display text-2xl text-foreground"
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
            <div className="mt-5 flex flex-wrap items-center gap-3 sm:hidden">
              <Button asChild variant="glow" size="xl" className="flex-1">
                <a href={DESTINATIONS.signup}>
                  Get started <ArrowRight aria-hidden="true" />
                </a>
              </Button>
              <Button asChild variant="quiet" size="xl" className="flex-1">
                <a href={DESTINATIONS.login}>Log in</a>
              </Button>
            </div>
            <div className="mt-5 flex items-center justify-between sm:hidden">
              <span className="eyebrow">Theme</span>
              <ThemeToggle />
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}
