import type { Locale } from '../locales/messages.ts'
import type { Role } from './payment.ts'

export const demoAccountPath = '/__pauseguard/demo'
export const accountCategories = { personal: 'Personal', professional: 'Professional', small_business: 'Small Business', enterprise: 'Enterprise' } as const
export const relationships = ['Family', 'Friend', 'Colleague', 'Other trusted contact'] as const
export type AccountCategory = keyof typeof accountCategories
export type Relationship = typeof relationships[number]
export type EnrollmentStatus = 'Pending' | 'Accepted' | 'Declined' | 'Revoked'

export interface DemoProfile {
  id: string
  role: Role
  sample: boolean
  name: string
  contact: string
  category: AccountCategory
  language: Locale
  largeText: boolean
  organization: string
  recurringSupplier: string
  thresholdPaise: number | null
  notifications: boolean
  quietStart: string
  quietEnd: string
  callConsent: boolean
  safeLock: boolean
}

export type ProfileUpdate = Partial<Omit<DemoProfile, 'id' | 'role' | 'sample'>>
export interface DemoSession { token: string; expiresAt: number; profile: DemoProfile }
export interface EnrollmentView { id: string; name: string; relationship: Relationship; status: EnrollmentStatus }

export function demoContact(value: unknown) {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim().toLowerCase()
  if (normalized.length <= 90 && (/^[a-z0-9][a-z0-9._+-]*@[a-z0-9][a-z0-9.-]*\.test$/.test(normalized) ||
      /^00000[0-9]{5}$/.test(normalized))) return normalized
}

export function demoName(value: unknown) {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim()
  if (normalized.length <= 64 && (normalized.match(/\p{L}/gu)?.length ?? 0) >= 2 &&
      /^[\p{L}\p{M} .'-]+$/u.test(normalized)) return normalized
}
