import { adminRequest, writeJson } from './adminApi'

export interface RetentionPolicyItem {
  table_name: string
  policy_type: string
  retention_threshold: string
  description: string
  eligible_count: number
}

export interface RetentionPoliciesResponse {
  policies: RetentionPolicyItem[]
  auto_cleanup_interval_seconds: number
  checked_at: string
}

export interface RetentionCleanupResponse {
  executed_at: string
  deleted_login_attempts: number
  deleted_expired_sessions: number
  deleted_idempotency_keys: number
  deleted_pending_messages: number
  deleted_telemetry_buckets: number
  deleted_sent_alert_emails: number
  deleted_health_samples: number
  total_deleted: number
}

export interface AnonymizeUserRequest {
  reason: string
  confirm_phrase: string
}

export interface AnonymizeUserResponse {
  user_id: string
  anonymized_email: string
  status: string
  anonymized_at: string
  preserved_financial_records: Record<string, number>
}

export interface LegalHoldRequest {
  hold: boolean
  reason: string
}

export interface LegalHoldResponse {
  user_id: string
  legal_hold: boolean
  reason: string | null
  updated_at: string
}

export async function fetchRetentionPolicies(signal?: AbortSignal) {
  return adminRequest<RetentionPoliciesResponse>(
    '/admin/privacy/retention-policies',
    { signal },
  )
}

export async function triggerRetentionCleanup() {
  return adminRequest<RetentionCleanupResponse>(
    '/admin/privacy/cleanup',
    writeJson('POST', {}),
  )
}

export async function fetchLegalHold(userId: string, signal?: AbortSignal) {
  return adminRequest<LegalHoldResponse>(`/admin/privacy/holds/${userId}`, {
    signal,
  })
}

export async function submitLegalHold(
  userId: string,
  hold: boolean,
  reason: string,
) {
  return adminRequest<LegalHoldResponse>(
    `/admin/privacy/holds/${userId}`,
    writeJson('POST', { hold, reason }),
  )
}

export async function submitAnonymizeUser(
  userId: string,
  reason: string,
  confirmPhrase: string,
) {
  return adminRequest<AnonymizeUserResponse>(
    `/admin/privacy/anonymize/${userId}`,
    writeJson('POST', { reason, confirm_phrase: confirmPhrase }),
  )
}
