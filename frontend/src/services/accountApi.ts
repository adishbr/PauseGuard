import { demoAccountPath, relationships } from '../types/account.ts'
import type {
  AccountCategory,
  AppRole,
  DemoProfile,
  DemoSession,
  EnrollmentView,
  ProfileUpdate,
  Relationship,
} from '../types/account.ts'
import type { Locale } from '../locales/messages.ts'
import { API_TIMEOUT_MS, apiUrl, isLoopbackHost, isRealBackendMode } from './backendMode.ts'
import { storageRead, storageWrite } from './demoSession.ts'

export const sessionExpired = 'pauseguard:session-expired'

export class AccountError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export const savedSession = (role: AppRole) => storageRead('sessionStorage', `pauseguard:demo:session:${role}`)
export const saveSession = (role: AppRole, token: string) => storageWrite('sessionStorage', `pauseguard:demo:session:${role}`, token)

async function request<T>(basePath: string, path: string, token?: string, body?: object, method = body ? 'POST' : 'GET'): Promise<T> {
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (body) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    const targetUrl = basePath.startsWith('/api/') ? apiUrl(basePath + path) : basePath + path
    response = await fetch(targetUrl, {
      method, headers, body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store', signal: AbortSignal.timeout(API_TIMEOUT_MS),
    })
  } catch {
    throw new AccountError(0, isRealBackendMode()
      ? 'FastAPI backend is unavailable. Check that the server is running and try again.'
      : 'Demo service unavailable. Check your connection and try again.')
  }
  const contentType = response.headers.get('content-type') ?? ''
  const data = contentType.includes('application/json') ? await response.json().catch(() => undefined) : undefined
  if (response.status === 401 && token) window.dispatchEvent(new CustomEvent(sessionExpired, { detail: token }))
  if (!response.ok || !data) {
    if (!isRealBackendMode() && (response.status === 404 || !contentType.includes('application/json'))) {
      throw new AccountError(
        response.status || 404,
        'The local demo server (/__pauseguard/demo) is not available on this host. Run locally with "npm run dev" or connect a FastAPI backend.',
      )
    }
    throw new AccountError(
      response.status,
      typeof data?.detail === 'string' ? data.detail : 'Could not complete this action.',
    )
  }
  return data as T
}

interface BackendActorProfile {
  user_id: string
  roles: string[]
  notification_preference_paise?: number | null
}

interface BackendDemoProfile {
  id: string
  role: string
  name: string
  contact: string
  sample?: boolean
  category?: string
  language?: string
  large_text?: boolean
  organization?: string
  recurring_supplier?: string
  threshold_paise?: number | null
  notifications?: boolean
  quiet_start?: string
  quiet_end?: string
  call_consent?: boolean
  safe_lock?: boolean
}

interface BackendDemoSessionResponse {
  token: string
  token_type?: string
  expires_in_seconds?: number
  expires_at?: number
  expiresAt?: number
  user_id: string
  role?: string
  roles: string[]
  profile: BackendDemoProfile
}

interface BackendSafeLockStatus {
  payer_id: string
  is_locked: boolean
  version: number
  updated_at: string
}

interface BackendGuardianEnroll {
  enrollment_id: string
  payer_id: string
  guardian_id: string
  relationship: string
  notification_channel: string
  status: string
  enrolled_at: string
}

interface BackendGuardianStatus {
  has_guardian: boolean
  enrollment: BackendGuardianEnroll | null
  guarded_payers: string[]
}

function resolveBackendRole(roles: string[]): AppRole {
  if (roles.includes('admin')) return 'admin'
  if (roles.includes('guardian')) return 'guardian'
  return 'payer'
}

function toRelationship(value: string): Relationship {
  const match = relationships.find((r) => r.toLowerCase() === value.toLowerCase())
  return match ?? 'Family'
}

function mapDemoSessionResponse(res: BackendDemoSessionResponse, safeLockOverride?: boolean): DemoSession {
  const serverRole = resolveBackendRole(res.roles)
  const p = res.profile
  const lang: Locale = p.language === 'hi' || p.language === 'kn' || p.language === 'te' ? p.language : 'en'
  const category: AccountCategory =
    p.category === 'professional' || p.category === 'small_business' || p.category === 'enterprise'
      ? p.category
      : 'personal'
  const expiresAt =
    typeof res.expires_at === 'number'
      ? res.expires_at
      : typeof res.expiresAt === 'number'
        ? res.expiresAt
        : Date.now() + (res.expires_in_seconds ?? 1800) * 1000

  return {
    token: res.token,
    expiresAt,
    profile: {
      id: String(res.user_id || p.id),
      role: serverRole,
      sample: Boolean(p.sample ?? true),
      name: p.name || `${serverRole} (${String(res.user_id).slice(-4)})`,
      contact: p.contact || String(res.user_id),
      category,
      language: lang,
      largeText: Boolean(p.large_text),
      organization: p.organization ?? '',
      recurringSupplier: p.recurring_supplier ?? '',
      thresholdPaise: p.threshold_paise ?? null,
      notifications: Boolean(p.notifications ?? true),
      quietStart: p.quiet_start ?? '',
      quietEnd: p.quiet_end ?? '',
      callConsent: Boolean(p.call_consent),
      safeLock: typeof safeLockOverride === 'boolean' ? safeLockOverride : Boolean(p.safe_lock),
    },
  }
}

async function fetchSafeLock(token: string, role: AppRole): Promise<boolean> {
  if (role !== 'payer') return false
  try {
    const lock = await request<BackendSafeLockStatus>('/api/v2', '/safe-lock', token)
    return Boolean(lock.is_locked)
  } catch {
    return false
  }
}

export interface V5SignupResult {
  user_id: string
  email: string
  full_name: string
  role: string
  email_verified: boolean
  requires_otp_verification: boolean
  challenge_id: string
  otp_expires_at: string
  is_mock_otp_delivery: boolean
  dev_otp_preview?: string | null
  message: string
}

export interface V5OtpChallengeResult {
  challenge_id: string
  contact: string
  purpose: string
  channel: string
  expires_at: string
  is_mock_delivery: boolean
  provider_name: string
  dev_otp_preview?: string | null
}

export interface V5OtpVerifyResult {
  challenge_id: string
  contact: string
  purpose: string
  verified: boolean
  email_verified: boolean
  verified_at: string
}

export interface V5LoginResponse {
  access_token: string
  token_type: string
  expires_at: string
  user_id: string
  email: string
  full_name: string
  role: string
  identity_verified: boolean
  is_synthetic: boolean
}

export interface V5IdentityAssurance {
  verified: boolean
  assurance_id?: string | null
  user_id: string
  trusted_person_ref?: string | null
  provider?: string | null
  assurance_level?: string | null
  is_mock_assurance: boolean
  revoked: boolean
  verified_at?: string | null
  expires_at?: string | null
}

export interface V5GuardianInvitation {
  invitation_id: string
  payer_id: string
  guardian_user_id?: string | null
  guardian_email: string
  relationship: string
  role_slot: 'primary' | 'backup'
  notification_channel: string
  status: string
  consent_confirmed: boolean
  expires_at: string
  accepted_at?: string | null
  revoked_at?: string | null
  created_at: string
  is_mock_invite_delivery: boolean
  dev_invite_token_preview?: string | null
}

export interface V5GuardianInvitationList {
  sent: V5GuardianInvitation[]
  received: V5GuardianInvitation[]
}

function writeV5UserMeta(userId: string, name: string, contact: string) {
  storageWrite('sessionStorage', `pauseguard:v5:user:${userId}`, JSON.stringify({ name, contact }))
}

function readV5UserMeta(userId: string): { name?: string; contact?: string } {
  try {
    const raw = storageRead('sessionStorage', `pauseguard:v5:user:${userId}`)
    return raw ? (JSON.parse(raw) as { name?: string; contact?: string }) : {}
  } catch {
    return {}
  }
}

async function fetchBackendSession(token: string): Promise<DemoSession> {
  if (!token.startsWith('pg_v5_')) {
    try {
      const demoRes = await request<BackendDemoSessionResponse>('/api/v2', '/demo/session', token)
      const role = resolveBackendRole(demoRes.roles)
      const safeLock = await fetchSafeLock(token, role)
      return mapDemoSessionResponse(demoRes, safeLock)
    } catch (error) {
      // Fallback to GET /api/v2/profile when PR #24 /demo/session endpoint is not present (404).
      if (!(error instanceof AccountError && error.status === 404)) throw error
    }
  }

  const actor = await request<BackendActorProfile>('/api/v2', '/profile', token)
  const serverRole = resolveBackendRole(actor.roles)
  const safeLock = await fetchSafeLock(token, serverRole)
  const meta = readV5UserMeta(actor.user_id)
  const profile: DemoProfile = {
    id: actor.user_id,
    role: serverRole,
    name: meta.name || `${serverRole.charAt(0).toUpperCase() + serverRole.slice(1)} (${actor.user_id.slice(-4)})`,
    contact: meta.contact || actor.user_id,
    category: 'personal',
    language: 'en',
    largeText: false,
    organization: '',
    recurringSupplier: '',
    thresholdPaise: actor.notification_preference_paise ?? null,
    notifications: true,
    quietStart: '',
    quietEnd: '',
    callConsent: false,
    safeLock,
    sample: false,
  }
  return {
    token,
    expiresAt: Date.now() + 12 * 60 * 60_000,
    profile,
  }
}

export function provisionedIdentityError(role: AppRole, contact: string): AccountError {
  const fallbackContact =
    role === 'admin'
      ? 'admin@pauseguard.test'
      : role === 'guardian'
        ? 'ravi@pauseguard.test'
        : 'asha@pauseguard.test'
  const sampleAction =
    role === 'admin'
      ? 'Open sample admin'
      : role === 'guardian'
        ? 'Open sample guardian'
        : 'Open sample payer'
  return new AccountError(
    404,
    `No provisioned ${role} identity matches "${contact}". Server-enforced auth allows ${fallbackContact} or "${sampleAction}" in FastAPI preview mode.`,
  )
}

export const accountApi = {
  login: async (role: AppRole, contact: string, sample = false): Promise<DemoSession> => {
    if (!isRealBackendMode()) {
      return request<DemoSession>(demoAccountPath, '/session', undefined, { role, contact, sample })
    }

    const trimmed = contact.trim()
    const looksLikeBearerToken =
      trimmed.startsWith('demo-token-') ||
      trimmed.startsWith('demo_token_') ||
      trimmed.startsWith('pg_demo_') ||
      trimmed.startsWith('eyJ')
    if (sample || !looksLikeBearerToken) {
      if (!isLoopbackHost()) {
        throw new AccountError(
          403,
          'Local demo session issuance is restricted to localhost/loopback environments.',
        )
      }
      try {
        const body = sample ? { role, sample: true } : { role, contact: trimmed }
        const demoRes = await request<BackendDemoSessionResponse>('/api/v2', '/demo/session', undefined, body)
        const session = mapDemoSessionResponse(demoRes)
        if (session.profile.role !== role) {
          throw new AccountError(403, `Forbidden: session belongs to role "${session.profile.role}", not "${role}".`)
        }
        return session
      } catch (error) {
        if (
          error instanceof AccountError &&
          error.status === 404 &&
          error.message.includes('No authorized synthetic demo identity') &&
          !sample &&
          trimmed
        ) {
          throw provisionedIdentityError(role, trimmed)
        }
        if (!(error instanceof AccountError && error.status === 404) || sample || !trimmed) {
          throw error
        }
        // If /api/v2/demo/session is not mounted (404), validate raw contact as a bearer token via /profile.
      }
    }

    const session = await fetchBackendSession(trimmed)
    if (session.profile.role !== role) {
      throw new AccountError(403, `Forbidden: token belongs to role "${session.profile.role}", not "${role}".`)
    }
    return session
  },

  register: async (role: AppRole, details: ProfileUpdate): Promise<DemoSession> => {
    if (!isRealBackendMode()) {
      return request<DemoSession>(demoAccountPath, '/register', undefined, { ...details, role })
    }
    throw new AccountError(
      501,
      'Self-service registration is only supported in standalone local mock mode. Use sample sign-in or a backend-issued bearer token.',
    )
  },

  session: async (token: string): Promise<DemoSession> => {
    if (!isRealBackendMode()) {
      return request<DemoSession>(demoAccountPath, '/session', token)
    }
    return fetchBackendSession(token)
  },

  logout: async (token: string) => {
    if (!isRealBackendMode()) {
      return request(demoAccountPath, '/session', token, undefined, 'DELETE')
    }
    try {
      if (token.startsWith('pg_v5_')) {
        return await request('/api/v2', '/auth/logout', token, {}, 'POST')
      }
      return await request('/api/v2', '/demo/session', token, undefined, 'DELETE')
    } catch (error) {
      if (error instanceof AccountError && (error.status === 404 || error.status === 401)) {
        return { signed_out: true }
      }
      throw error
    }
  },

  v5Signup: async (payload: {
    email: string
    password: string
    fullName: string
    role: 'payer' | 'guardian'
  }): Promise<V5SignupResult> => {
    return request<V5SignupResult>('/api/v2', '/auth/signup', undefined, {
      email: payload.email.trim(),
      password: payload.password,
      full_name: payload.fullName.trim(),
      role: payload.role,
    })
  },

  v5RequestOtp: async (payload: {
    contact: string
    purpose: 'signup_email' | 'login_step_up' | 'guardian_invite'
    channel?: 'email' | 'sms_stub'
  }): Promise<V5OtpChallengeResult> => {
    return request<V5OtpChallengeResult>('/api/v2', '/auth/otp/challenge', undefined, {
      contact: payload.contact.trim(),
      purpose: payload.purpose,
      channel: payload.channel ?? 'email',
    })
  },

  v5VerifyOtp: async (payload: { challengeId: string; otpCode: string }): Promise<V5OtpVerifyResult> => {
    return request<V5OtpVerifyResult>('/api/v2', '/auth/otp/verify', undefined, {
      challenge_id: payload.challengeId,
      otp_code: payload.otpCode.trim(),
    })
  },

  v5Login: async (role: AppRole, email: string, password: string): Promise<DemoSession> => {
    const res = await request<V5LoginResponse>('/api/v2', '/auth/login', undefined, {
      email: email.trim(),
      password,
    })
    const serverRole = resolveBackendRole([res.role])
    if (serverRole !== role) {
      throw new AccountError(403, `Forbidden: account holds role "${serverRole}", not "${role}".`)
    }
    writeV5UserMeta(res.user_id, res.full_name, res.email)
    const safeLock = await fetchSafeLock(res.access_token, serverRole)
    const parsedExpiry = Date.parse(res.expires_at)
    return {
      token: res.access_token,
      expiresAt: Number.isFinite(parsedExpiry) ? parsedExpiry : Date.now() + 12 * 60 * 60_000,
      profile: {
        id: res.user_id,
        role: serverRole,
        sample: false,
        name: res.full_name,
        contact: res.email,
        category: 'personal',
        language: 'en',
        largeText: false,
        organization: '',
        recurringSupplier: '',
        thresholdPaise: null,
        notifications: true,
        quietStart: '',
        quietEnd: '',
        callConsent: false,
        safeLock,
      },
    }
  },

  identityStatus: async (token: string): Promise<V5IdentityAssurance> => {
    return request<V5IdentityAssurance>('/api/v2', '/identity/status', token)
  },

  identityVerify: async (
    token: string,
    payload: { fullName: string; syntheticDocumentRef: string; consentConfirmed: boolean },
  ): Promise<V5IdentityAssurance> => {
    return request<V5IdentityAssurance>('/api/v2', '/identity/verify', token, {
      provider: 'synthetic_local_idp',
      full_name: payload.fullName.trim(),
      synthetic_document_ref: payload.syntheticDocumentRef.trim(),
      consent_confirmed: payload.consentConfirmed,
    })
  },

  v5Invitations: async (token: string): Promise<V5GuardianInvitationList> => {
    return request<V5GuardianInvitationList>('/api/v2', '/guardian/invitations', token)
  },

  createV5Invitation: async (
    token: string,
    payload: {
      guardianEmail: string
      relationship: string
      roleSlot?: 'primary' | 'backup'
      notificationChannel?: 'in_app' | 'email' | 'push' | 'sms'
    },
  ): Promise<V5GuardianInvitation> => {
    return request<V5GuardianInvitation>('/api/v2', '/guardian/invitations', token, {
      guardian_email: payload.guardianEmail.trim(),
      relationship: payload.relationship.trim() || 'family',
      role_slot: payload.roleSlot ?? 'primary',
      notification_channel: payload.notificationChannel ?? 'in_app',
    })
  },

  acceptV5Invitation: async (
    token: string,
    invitationId: string,
    payload: { inviteToken: string; otpChallengeId: string; otpCode: string; explicitConsent: boolean },
  ): Promise<V5GuardianInvitation> => {
    return request<V5GuardianInvitation>('/api/v2', `/guardian/invitations/${encodeURIComponent(invitationId)}/accept`, token, {
      invite_token: payload.inviteToken.trim(),
      otp_challenge_id: payload.otpChallengeId.trim(),
      otp_code: payload.otpCode.trim(),
      explicit_consent: payload.explicitConsent,
    })
  },

  declineV5Invitation: async (token: string, invitationId: string): Promise<V5GuardianInvitation> => {
    return request<V5GuardianInvitation>('/api/v2', `/guardian/invitations/${encodeURIComponent(invitationId)}/decline`, token, {})
  },

  revokeV5Invitation: async (token: string, invitationId: string): Promise<V5GuardianInvitation> => {
    return request<V5GuardianInvitation>('/api/v2', `/guardian/invitations/${encodeURIComponent(invitationId)}/revoke`, token, {})
  },

  suspendV5Invitation: async (token: string, invitationId: string, reason = 'suspected_compromise'): Promise<V5GuardianInvitation> => {
    return request<V5GuardianInvitation>('/api/v2', `/guardian/invitations/${encodeURIComponent(invitationId)}/suspend`, token, { reason })
  },

  save: async (token: string, changes: ProfileUpdate): Promise<DemoProfile> => {
    if (!isRealBackendMode()) {
      return request<DemoProfile>(demoAccountPath, '/profile', token, changes)
    }
    if (typeof changes.safeLock === 'boolean') {
      await request<BackendSafeLockStatus>('/api/v2', '/safe-lock', token, { is_locked: changes.safeLock })
    }
    const refreshed = await fetchBackendSession(token)
    return refreshed.profile
  },

  enrollments: async (token: string): Promise<EnrollmentView[]> => {
    if (!isRealBackendMode()) {
      return request<EnrollmentView[]>(demoAccountPath, '/enrollment', token)
    }
    const status = await request<BackendGuardianStatus>('/api/v2', '/guardian/status', token)
    const views: EnrollmentView[] = []
    if (status.enrollment) {
      const e = status.enrollment
      views.push({
        id: e.enrollment_id,
        name: e.guardian_id,
        relationship: toRelationship(e.relationship),
        status: e.status === 'active' ? 'Accepted' : 'Revoked',
      })
    }
    for (const payerId of status.guarded_payers) {
      views.push({
        id: `guarded:${payerId}`,
        name: payerId,
        relationship: 'Family',
        status: 'Accepted',
      })
    }
    return views
  },

  enrollmentAction: async (token: string, body: object): Promise<EnrollmentView[]> => {
    if (!isRealBackendMode()) {
      return request<EnrollmentView[]>(demoAccountPath, '/enrollment', token, body)
    }
    const payload = body as Record<string, unknown>
    const action = payload.action
    if (action === 'enroll' || action === 'accept') {
      await request<BackendGuardianEnroll>('/api/v2', '/guardian/enroll', token, {
        guardian_id: String(payload.guardianContact || payload.guardian_id || ''),
        relationship: String(payload.relationship || 'family'),
        notification_channel: 'in_app',
        opt_in_confirmed: Boolean(payload.consent ?? true),
      })
    } else if (action === 'revoke' || action === 'withdraw') {
      await request('/api/v2', '/guardian/revoke', token, {})
    }
    return accountApi.enrollments(token)
  },

  review: async (token: string, reference: string): Promise<{ id: string | null }> => {
    if (!isRealBackendMode()) {
      return request<{ id: string | null }>(demoAccountPath, `/reviews?reference=${encodeURIComponent(reference)}`, token)
    }
    try {
      if (!reference) {
        const dashboard = await request<{ pending_reviews?: Array<{ id?: string }> }>(
          '/api/v2',
          '/guardian/dashboard',
          token,
        )
        const pendingId = dashboard.pending_reviews?.[0]?.id
        return { id: typeof pendingId === 'string' && pendingId ? pendingId : null }
      }
      await request('/api/v2', `/payments/${encodeURIComponent(reference)}`, token)
      return { id: reference }
    } catch (error) {
      if (error instanceof AccountError && (error.status === 404 || error.status === 403)) {
        return { id: null }
      }
      throw error
    }
  },
}
