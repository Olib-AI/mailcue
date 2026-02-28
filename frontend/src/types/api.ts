// =============================================================================
// API Response Types — matching the backend Pydantic schemas
// =============================================================================

export interface User {
  id: string;
  username: string;
  email: string;
  is_admin: boolean;
  created_at: string;
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

// --- Email Types ---

export interface EmailAttachment {
  filename: string;
  content_type: string;
  size: number;
  content_id: string | null;
}

export interface EmailSummary {
  uid: string;
  mailbox: string;
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

export interface SendEmailRequest {
  from_address: string;
  to_addresses: string[];
  cc_addresses?: string[];
  subject: string;
  body: string;
  body_type: "html" | "plain";
  sign?: boolean;
  encrypt?: boolean;
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

// --- SSE Event Types ---

export type SSEEventType =
  | "email.received"
  | "email.deleted"
  | "mailbox.created"
  | "mailbox.deleted"
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

export type FolderName = "INBOX" | "Sent" | "Drafts" | "Trash";

export const FOLDERS: { name: FolderName; label: string }[] = [
  { name: "INBOX", label: "Inbox" },
  { name: "Sent", label: "Sent" },
  { name: "Drafts", label: "Drafts" },
  { name: "Trash", label: "Trash" },
];

// --- GPG Types ---

export type SignatureStatus = "valid" | "invalid" | "no_public_key" | "expired_key" | "error";

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

// --- API Error ---

export interface APIError {
  detail: string;
  status_code?: number;
}
