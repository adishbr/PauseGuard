import { cn } from "@/lib/utils";

/** Two pause bars with a thread of light passing between them. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-7", className)}>
      <defs>
        <linearGradient id="pg-mark-bar" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" style={{ stopColor: "var(--art-cyan)" }} />
          <stop offset="1" style={{ stopColor: "var(--art-violet)" }} />
        </linearGradient>
      </defs>
      <rect x="7" y="5" width="6.5" height="22" rx="3.25" fill="url(#pg-mark-bar)" opacity="0.95" />
      <rect x="18.5" y="5" width="6.5" height="22" rx="3.25" fill="url(#pg-mark-bar)" opacity="0.75" />
      <path
        d="M2 20 C 10 13, 13 22, 16 17 S 24 9, 30 13"
        fill="none"
        stroke="var(--art-core)"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <BrandMark />
      <span className="font-sans text-[1.05rem] font-semibold tracking-[-0.01em]">PauseGuard</span>
    </span>
  );
}
