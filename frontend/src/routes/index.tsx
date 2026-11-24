import { createFileRoute } from "@tanstack/react-router";
import {
  ArrowDown,
  ArrowRight,
  EyeOff,
  Hourglass,
  ScanSearch,
  UserRoundCheck,
  CircleCheck,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { PauseArtwork } from "@/components/pauseguard/pause-artwork";
import { SiteHeader } from "@/components/pauseguard/site-header";
import { Wordmark } from "@/components/pauseguard/brand-mark";
import { DESTINATIONS } from "@/components/pauseguard/destinations";

const TITLE = "PauseGuard — A pause can protect a payment";
const DESCRIPTION =
  "Spot warning signs, take a moment to verify, and involve someone you trust when you need a second opinion before a UPI payment.";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: TITLE },
      { name: "description", content: DESCRIPTION },
      { name: "robots", content: "noindex, nofollow" },
      { property: "og:title", content: TITLE },
      { property: "og:description", content: DESCRIPTION },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

const STEPS = [
  {
    n: "01",
    who: "Payer",
    Icon: ScanSearch,
    title: "Check the payment",
    text: "Enter the details and see if the request has warning signs worth a closer look.",
  },
  {
    n: "02",
    who: "Guardian · optional",
    Icon: UserRoundCheck,
    title: "Get a second look",
    text: "When a review is needed, an enrolled guardian can help you assess the request.",
  },
  {
    n: "03",
    who: "Payer",
    Icon: CircleCheck,
    title: "Make your decision",
    text: "Review the outcome and decide whether to stop or confirm an eligible payment.",
  },
] as const;

const CONTAINER = "mx-auto w-full max-w-[90rem] px-5 sm:px-8 lg:px-12";

function Index() {
  return (
    <div className="relative min-h-screen overflow-x-clip">
      <a
        href="#main"
        className="sr-only z-50 rounded-full bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to content
      </a>
      <SiteHeader />
      <main id="main" tabIndex={-1} className="outline-none">
        <Hero />
        <HowItWorks />
        <Privacy />
      </main>
      <SiteFooter />
    </div>
  );
}

function Hero() {
  return (
    <section aria-labelledby="hero-title" className="relative">
      <div
        className={`${CONTAINER} grid grid-cols-1 items-center gap-y-4 pb-20 pt-4 lg:min-h-[calc(100svh-5rem)] lg:grid-cols-12 lg:pb-16 lg:pt-0`}
      >
        <div className="relative order-1 lg:order-2 lg:col-span-7 lg:col-start-6 lg:row-start-1 lg:-mr-10 xl:-mr-16">
          <PauseArtwork className="mx-auto w-full max-w-[24rem] sm:max-w-[32rem] lg:ml-auto lg:mr-0 lg:w-[min(100%,calc((100svh-6rem)*1.05))] lg:max-w-none" />
        </div>

        <div className="pg-rise relative z-10 order-2 lg:order-1 lg:col-span-6 lg:col-start-1 lg:row-start-1">
          <p className="eyebrow">UPI payment protection</p>
          <h1
            id="hero-title"
            className="mt-5 font-display text-[clamp(2.75rem,8.4vw,7.25rem)] font-normal leading-[0.94] tracking-[-0.025em] text-balance"
          >
            A pause can protect <em className="text-luminous pr-[0.06em]">a payment.</em>
          </h1>
          <p className="mt-7 max-w-[30rem] text-base leading-relaxed text-muted-foreground sm:text-lg">
            Spot warning signs, take a moment to verify, and involve someone you trust when you need
            a second opinion.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Button asChild variant="glow" size="xl">
              <a href={DESTINATIONS.signup}>
                Get started <ArrowRight aria-hidden="true" />
              </a>
            </Button>
            <Button asChild variant="quiet" size="xl">
              <a href={DESTINATIONS.howItWorks}>
                See how it works <ArrowDown aria-hidden="true" />
              </a>
            </Button>
          </div>
          <PreviewNote className="mt-12" />
        </div>
      </div>
      {/* the ribbon continues down the page */}
      <div
        aria-hidden="true"
        className="ribbon-line-vertical absolute bottom-0 left-1/2 h-28 w-px opacity-70"
      />
    </section>
  );
}

function PreviewNote({ className = "" }: { className?: string }) {
  return (
    <p className={`inline-flex items-center gap-2.5 text-sm text-muted-foreground ${className}`}>
      <span aria-hidden="true" className="relative inline-flex size-2">
        <span className="animate-pulse-dot absolute inset-0 rounded-full bg-cyan" />
      </span>
      Preview environment. No funds move.
    </p>
  );
}

function StepNode({ Icon }: { Icon: (typeof STEPS)[number]["Icon"] }) {
  return (
    <span className="relative z-10 grid size-12 place-items-center rounded-full border border-[var(--glass-edge)] bg-background shadow-[0_0_24px_-6px_var(--art-glow-cyan)]">
      <Icon className="size-5 text-cyan" aria-hidden="true" strokeWidth={1.6} />
    </span>
  );
}

function HowItWorks() {
  return (
    <section id="how-it-works" aria-labelledby="steps-title" className="relative scroll-mt-24">
      <div className={`${CONTAINER} pb-24 pt-20 lg:pb-36 lg:pt-16`}>
        <div className="grid gap-6 lg:grid-cols-12 lg:items-end">
          <div className="lg:col-span-7">
            <p className="eyebrow">How it works</p>
            <h2
              id="steps-title"
              className="mt-4 font-display text-[clamp(2.4rem,5.4vw,4.75rem)] font-normal leading-[0.98] tracking-[-0.02em] text-balance"
            >
              From a warning <span className="italic text-muted-foreground">to a decision.</span>
            </h2>
          </div>
          <p className="max-w-sm text-muted-foreground lg:col-span-4 lg:col-start-9">
            Three steps. A guardian only joins when a review is needed, and the final call is always
            yours.
          </p>
        </div>

        <div className="relative mt-16 lg:mt-24">
          {/* ribbon thread through the steps */}
          <svg
            aria-hidden="true"
            viewBox="0 0 1200 48"
            preserveAspectRatio="none"
            className="absolute inset-x-0 top-0 hidden h-12 w-full overflow-visible lg:block"
          >
            <defs>
              <linearGradient id="pg-thread" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" style={{ stopColor: "var(--art-cyan)", stopOpacity: 0 }} />
                <stop offset="0.15" style={{ stopColor: "var(--art-cyan)" }} />
                <stop offset="0.5" style={{ stopColor: "var(--art-core)" }} />
                <stop offset="0.85" style={{ stopColor: "var(--art-violet)" }} />
                <stop offset="1" style={{ stopColor: "var(--art-violet)", stopOpacity: 0 }} />
              </linearGradient>
            </defs>
            {[0, 1, 2].map((i) => (
              <path
                key={i}
                d={`M0 24 C 200 ${12 + i * 6}, 330 ${36 - i * 6}, 520 24 S 900 ${12 + i * 6}, 1200 ${24 + (i - 1) * 3}`}
                fill="none"
                stroke="url(#pg-thread)"
                strokeWidth={i === 1 ? 1.4 : 0.8}
                strokeOpacity={i === 1 ? 0.9 : 0.45}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
          <div
            aria-hidden="true"
            className="ribbon-line-vertical absolute bottom-6 left-6 top-6 w-px lg:hidden"
          />

          <ol className="relative grid gap-12 lg:grid-cols-3 lg:gap-10">
            {STEPS.map(({ n, who, Icon, title, text }) => (
              <li key={n} className="relative grid grid-cols-[3rem_1fr] gap-x-5 lg:block">
                <StepNode Icon={Icon} />
                <div className="lg:mt-10">
                  <div className="flex items-baseline gap-3">
                    <span className="font-mono text-xs text-cyan">{n}</span>
                    <span className="eyebrow">{who}</span>
                  </div>
                  <h3 className="mt-3 font-display text-[clamp(1.75rem,2.6vw,2.4rem)] font-normal leading-tight">
                    {title}
                  </h3>
                  <p className="mt-3 max-w-[22rem] leading-relaxed text-muted-foreground">{text}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}

function Privacy() {
  return (
    <section id="privacy" aria-labelledby="privacy-title" className="relative scroll-mt-24">
      <div className={`${CONTAINER} pb-24 lg:pb-36`}>
        <div className="glass-panel grain relative overflow-hidden rounded-[2rem] px-6 py-16 sm:px-14 lg:rounded-[2.5rem] lg:px-20 lg:py-24">
          {/* the pause bars, now framing the promise */}
          <div
            aria-hidden="true"
            className="glass-bar absolute -left-7 bottom-10 top-10 w-12 opacity-80 sm:-left-6 sm:w-16 lg:left-10 lg:w-24 lg:opacity-100"
          />
          <div
            aria-hidden="true"
            className="glass-bar absolute -right-7 bottom-10 top-10 w-12 opacity-80 sm:-right-6 sm:w-16 lg:right-10 lg:w-24 lg:opacity-100"
          />
          <div
            aria-hidden="true"
            className="ribbon-line absolute inset-x-0 top-[58%] h-px opacity-50"
          />
          <div aria-hidden="true" className="canvas-glow absolute inset-0 opacity-40 blur-3xl" />

          <div className="relative mx-auto max-w-3xl">
            <p className="eyebrow text-center">Privacy</p>
            <h2
              id="privacy-title"
              className="mt-4 text-center font-display text-[clamp(2.3rem,5.2vw,4.5rem)] font-normal leading-[0.98] tracking-[-0.02em] text-balance"
            >
              Your payment. <em className="text-luminous">Your decision.</em>
            </h2>
            <p className="mx-auto mt-6 max-w-xl text-center leading-relaxed text-muted-foreground sm:text-lg">
              Guardians see a limited review request. Your recipient, amount, and payment purpose
              stay private.
            </p>

            <div className="mt-12 grid gap-4 sm:grid-cols-2">
              <div className="rounded-2xl border border-hairline bg-background/50 p-6 backdrop-blur-md">
                <p className="eyebrow">A guardian sees</p>
                <p className="mt-4 font-display text-2xl leading-snug">A limited review request</p>
              </div>
              <div className="rounded-2xl border border-hairline bg-background/50 p-6 backdrop-blur-md">
                <p className="eyebrow inline-flex items-center gap-2">
                  <EyeOff className="size-3.5" aria-hidden="true" /> Stays private
                </p>
                <ul className="mt-4 flex flex-wrap gap-2">
                  {["Recipient", "Amount", "Payment purpose"].map((item) => (
                    <li
                      key={item}
                      className="rounded-full border border-[var(--glass-edge)] px-3 py-1 text-sm text-foreground"
                    >
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="mt-4 flex items-start gap-4 rounded-2xl border border-hairline bg-background/50 p-6 backdrop-blur-md">
              <span className="grid size-10 shrink-0 place-items-center rounded-full bg-violet/15 text-violet">
                <Hourglass className="size-4" aria-hidden="true" />
              </span>
              <p className="leading-relaxed">
                <span className="font-semibold">If a guardian review times out,</span>{" "}
                <span className="text-muted-foreground">the payment stays on hold.</span>
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

const FOOTER_LINKS = [
  { href: DESTINATIONS.privacy, label: "Privacy" },
  { href: DESTINATIONS.help, label: "Help" },
  { href: DESTINATIONS.guardian, label: "Guardian portal" },
  { href: DESTINATIONS.admin, label: "Admin & Razorpay sandbox" },
] as const;

function SiteFooter() {
  return (
    <footer className="border-t border-hairline">
      <div
        className={`${CONTAINER} flex flex-col gap-8 py-12 lg:flex-row lg:items-center lg:justify-between`}
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:gap-8">
          <a
            href={DESTINATIONS.home}
            aria-label="PauseGuard home"
            className="self-start rounded-md"
          >
            <Wordmark />
          </a>
          <PreviewNote />
        </div>
        <nav aria-label="Footer navigation">
          <ul className="flex flex-wrap gap-x-7 gap-y-3">
            {FOOTER_LINKS.map((link) => (
              <li key={link.href}>
                <a
                  href={link.href}
                  className="rounded-md text-sm text-muted-foreground transition-colors hover:text-foreground"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </footer>
  );
}
