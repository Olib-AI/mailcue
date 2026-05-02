// =============================================================================
// API Response Types — matching the backend Pydantic schemas
// =============================================================================

export interface User {
  id: string;
  username: string;
  email: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  totp_enabled: boolean;
  max_mailboxes: number;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface RefreshResponse {
  access_token: string;
  user: User;
}

// --- Auth Security Types ---

export interface LoginStepResponse {
  requires_2fa: boolean;
  temp_token: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface TOTPSetupResponse {
  secret: string;
  qr_code: string;
  provisioning_uri: string;
}

export interface TwoFactorVerifyRequest {
  code: string;
  temp_token: string;
}

export function isLoginStepResponse(
  data: LoginResponse | LoginStepResponse,
): data is LoginStepResponse {
  return (
    "requires_2fa" in data && (data as LoginStepResponse).requires_2fa === true
  );
}

// --- Email Types ---

export interface EmailAttachment {
  filename: string;
  content_type: string;
  size: number;
  content_id: string | null;
  part_id: string;
}

export interface EmailSummary {
  uid: string;
  mailbox: string;
  from_name: string;
  from_address: string;
  to_addresses: string[];
  subject: string;
  date: string;
  has_attachments: boolean;
  is_read: boolean;
  preview: string;
  message_id: string;
  size: number;
  is_signed: boolean;
  is_encrypted: boolean;
  // Threading fields — populated by the backend when the list is fetched with
  // `thread_view=true`. Optional because older API builds and non-thread queries
  // omit them.
  in_reply_to?: string | null;
  references?: string[];
  thread_id?: string;
}

export interface EmailDetail extends EmailSummary {
  html_body: string | null;
  text_body: string | null;
  cc_addresses: string[];
  bcc_addresses: string[];
  raw_headers: Record<string, string>;
  attachments: EmailAttachment[];
  gpg: GpgEmailInfo | null;
}

export interface EmailListResponse {
  total: number;
  page: number;
  page_size: number;
  emails: EmailSummary[];
  has_more: boolean;
}

export interface SendAttachment {
  filename: string;
  content_type: string;
  data: string; // base64-encoded
}

export interface SendEmailRequest {
  from_address: string;
  from_name?: string;
  to_addresses: string[];
  cc_addresses?: string[];
  bcc_addresses?: string[];
  subject: string;
  body: string;
  body_type: "html" | "plain";
  attachments?: SendAttachment[];
  sign?: boolean;
  encrypt?: boolean;
  in_reply_to?: string;
  references?: string[];
}

export interface InjectEmailRequest {
  mailbox: string;
  from_address: string;
  to_addresses: string[];
  subject: string;
  html_body?: string;
  text_body?: string;
  headers?: Record<string, string>;
}

// --- Mailbox Types ---

export interface Mailbox {
  id: string;
  address: string;
  username: string;
  display_name: string;
  domain: string;
  is_active: boolean;
  created_at: string;
  email_count: number;
  unread_count: number;
  junk_count: number;
  signature: string;
  owner_id: string | null;
}

export interface CreateMailboxRequest {
  username: string;
  password: string;
  domain?: string;
  display_name?: string;
}

export interface MailboxListResponse {
  mailboxes: Mailbox[];
  total: number;
}

// --- User Management Types ---

export interface UserListResponse {
  users: User[];
  total: number;
}

export interface RegisterUserRequest {
  username: string;
  email: string;
  password: string;
  is_admin?: boolean;
  max_mailboxes?: number;
}

export interface UpdateUserRequest {
  max_mailboxes?: number;
  is_active?: boolean;
  is_admin?: boolean;
}

// --- SSE Event Types ---

export type SSEEventType =
  | "email.received"
  | "email.sent"
  | "email.deleted"
  | "mailbox.created"
  | "mailbox.deleted"
  | "sandbox.message"
  | "heartbeat";

export interface SSEEvent {
  event: SSEEventType;
  data: Record<string, unknown>;
}

export interface EmailReceivedEvent {
  mailbox: string;
  uid: string;
  from: string;
  subject: string;
}

export interface EmailDeletedEvent {
  mailbox: string;
  uid: string;
}

export interface MailboxEvent {
  address: string;
}

// --- Folder Types ---

export type FolderName = "INBOX" | "Sent" | "Drafts" | "Trash" | "Junk";

export const FOLDERS: { name: FolderName; label: string }[] = [
  { name: "INBOX", label: "Inbox" },
  { name: "Sent", label: "Sent" },
  { name: "Drafts", label: "Drafts" },
  { name: "Trash", label: "Trash" },
  { name: "Junk", label: "Junk" },
];

// --- GPG Types ---

export type SignatureStatus =
  | "valid"
  | "invalid"
  | "no_public_key"
  | "expired_key"
  | "error";

export interface GpgEmailInfo {
  is_signed: boolean;
  is_encrypted: boolean;
  signature_status: SignatureStatus | null;
  signer_fingerprint: string | null;
  signer_key_id: string | null;
  signer_uid: string | null;
  decrypted: boolean;
  encryption_key_ids: string[];
}

export interface GpgKey {
  id: string;
  mailbox_address: string;
  fingerprint: string;
  key_id: string;
  uid_name: string | null;
  uid_email: string | null;
  algorithm: string | null;
  key_length: number | null;
  created_at: string;
  expires_at: string | null;
  is_private: boolean;
  is_active: boolean;
}

export interface GpgKeyListResponse {
  keys: GpgKey[];
  total: number;
}

export interface GenerateGpgKeyRequest {
  mailbox_address: string;
  name?: string;
  algorithm?: "RSA" | "ECC";
  key_length?: number;
  expire?: string;
}

export interface ImportGpgKeyRequest {
  armored_key: string;
  mailbox_address?: string;
}

export interface GpgKeyExportResponse {
  mailbox_address: string;
  fingerprint: string;
  public_key: string;
}

// --- Domain Types ---

export interface Domain {
  id: number;
  name: string;
  is_active: boolean;
  created_at: string;
  dkim_selector: string;
  mx_verified: boolean;
  spf_verified: boolean;
  dkim_verified: boolean;
  dmarc_verified: boolean;
  mta_sts_verified: boolean;
  tls_rpt_verified: boolean;
  last_dns_check: string | null;
  all_verified: boolean;
}

export interface DnsRecordInfo {
  record_type: string;
  hostname: string;
  expected_value: string;
  verified: boolean;
  current_value: string | null;
  purpose: string;
  drift?: boolean;
  last_checked_at?: string | null;
  last_verified_at?: string | null;
}

export interface DomainDetail extends Domain {
  dns_records: DnsRecordInfo[];
  dkim_public_key_txt: string | null;
}

export interface DomainDnsState {
  domain: string;
  records: DnsRecordInfo[];
  has_drift: boolean;
  has_missing: boolean;
  last_dns_check: string | null;
}

export interface DomainListResponse {
  domains: Domain[];
  total: number;
}

export interface CreateDomainRequest {
  name: string;
  dkim_selector?: string;
}

export interface DnsCheckResponse {
  mx_verified: boolean;
  spf_verified: boolean;
  dkim_verified: boolean;
  dmarc_verified: boolean;
  mta_sts_verified: boolean;
  tls_rpt_verified: boolean;
  all_verified: boolean;
  dns_records: DnsRecordInfo[];
}

// --- Certificate Types ---

export interface CertificateDN {
  common_name: string | null;
  organization: string | null;
  organizational_unit: string | null;
  country: string | null;
  state: string | null;
  locality: string | null;
  email: string | null;
  dn: string;
}

export interface CertificateDetail {
  fingerprint_sha256: string;
  fingerprint_sha1: string;
  serial_number: string;
  version: string;
  signature_algorithm: string;
  subject: CertificateDN;
  issuer: CertificateDN;
  validity: {
    not_before: string;
    not_after: string;
  };
  san: {
    dns_names: string[];
    ip_addresses: string[];
    emails: string[];
  };
  is_ca: boolean;
  key_usage: string[];
  extended_key_usage: string[];
  public_key_algorithm: string;
  public_key_size: number;
}

export interface CertificateInfo {
  server: CertificateDetail;
  ca: CertificateDetail | null;
}

// --- Server Settings Types ---

export interface ServerSettings {
  hostname: string;
}

export interface UpdateServerSettingsRequest {
  hostname: string;
}

// --- API Key Types ---

export interface APIKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  is_active: boolean;
}

export interface APIKeyCreated extends APIKey {
  key: string;
}

export interface CreateAPIKeyRequest {
  name: string;
}

// --- TLS Certificate Types ---

export interface TlsCertificateStatus {
  configured: boolean;
  common_name: string | null;
  san_dns_names: string[];
  not_before: string | null;
  not_after: string | null;
  fingerprint_sha256: string | null;
  uploaded_at: string | null;
}

export interface UploadTlsCertificateRequest {
  certificate: string;
  private_key: string;
  ca_certificate?: string;
}

// --- Forwarding Rule Types ---

export type ForwardingRuleActionType = "smtp_forward" | "webhook";

export interface ForwardingRuleActionConfig {
  to_address?: string;
  url?: string;
  method?: string;
  headers?: Record<string, string>;
}

export interface ForwardingRule {
  id: string;
  name: string;
  enabled: boolean;
  match_from: string | null;
  match_to: string | null;
  match_subject: string | null;
  match_mailbox: string | null;
  action_type: ForwardingRuleActionType;
  action_config: ForwardingRuleActionConfig;
  created_at: string;
  updated_at: string;
}

export interface ForwardingRuleListResponse {
  rules: ForwardingRule[];
  total: number;
}

export interface CreateForwardingRuleRequest {
  name: string;
  enabled: boolean;
  match_from?: string | null;
  match_to?: string | null;
  match_subject?: string | null;
  match_mailbox?: string | null;
  action_type: ForwardingRuleActionType;
  action_config: ForwardingRuleActionConfig;
}

export interface UpdateForwardingRuleRequest {
  name?: string;
  enabled?: boolean;
  match_from?: string | null;
  match_to?: string | null;
  match_subject?: string | null;
  match_mailbox?: string | null;
  action_type?: ForwardingRuleActionType;
  action_config?: ForwardingRuleActionConfig;
}

export interface TestForwardingRuleResponse {
  matched: boolean;
  details: string;
}

// --- Alias Types ---

export interface Alias {
  id: string;
  source_address: string;
  destination_address: string;
  domain: string;
  is_catch_all: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AliasListResponse {
  aliases: Alias[];
  total: number;
}

export interface CreateAliasRequest {
  source_address: string;
  destination_address: string;
  is_catch_all?: boolean;
  enabled?: boolean;
}

export interface UpdateAliasRequest {
  source_address?: string;
  destination_address?: string;
  is_catch_all?: boolean;
  enabled?: boolean;
}

// --- Production Status Types ---

export interface ProductionStatus {
  mode: string;
  tls_configured: boolean;
  domains_configured: number;
  domains_verified: number;
  postfix_strict_mode: boolean;
  dovecot_tls_required: boolean;
  secure_cookies: boolean;
  acme_configured: boolean;
}

// --- Flag Types ---

export interface UpdateFlagsRequest {
  seen: boolean;
}

// --- Spam Types ---

export interface SpamActionRequest {
  folder: string;
}

// --- API Error ---

export interface APIError {
  detail: string;
  status_code?: number;
}
