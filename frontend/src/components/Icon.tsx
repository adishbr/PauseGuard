const paths = {
  shield: <><path d="M12 22s7-3.6 7-10V5l-7-3-7 3v7c0 6.4 7 10 7 10Z" /><path d="m9 12 2 2 4-4" /></>,
  arrow: <><path d="M4 12h15m-6-6 6 6-6 6" /></>,
  external: <><path d="M13 5h6v6m0-6-8 8" /><path d="M19 13v6H5V5h6" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 1 1 8 0v3m-4 4v3" /></>,
  users: <><circle cx="9" cy="8" r="3" /><path d="M3 20v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2M16 5a3 3 0 0 1 0 6m2 3a4 4 0 0 1 3 4v2" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  activity: <path d="M3 12h5l3-7 3 14 3-7h4" />,
} as const

export function Icon({ name, size = 22 }: { name: keyof typeof paths, size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name]}
    </svg>
  )
}
