export type BodyType = 'plain' | 'html';

export interface Attachment {
  filename: string;
  contentType: string;
  content: Buffer | Uint8Array | string;
}

export interface SendEmailParams {
  from: string;
  fromName?: string;
  to: string[];
  cc?: string[];
  subject: string;
  text?: string;
  html?: string;
  body?: string;
  bodyType?: BodyType;
  attachments?: Attachment[];
  sign?: boolean;
  encrypt?: boolean;
  replyTo?: string;
  inReplyTo?: string;
  references?: string[];
  bulk?: boolean;
  listUnsubscribe?: string;
  listUnsubscribePost?: string;
}

export interface SendResult {
  message: string;
  messageId: string;
}

export interface ListEmailsParams {
  mailbox: string;
  folder?: string;
  page?: number;
  pageSize?: number;
  search?: string;
  sort?: string;
}

export interface EmailSummary {
  uid: string;
  mailbox: string;
  fromAddress: string;
  toAddresses: string[];
  subject: string;
  date: string | null;
  hasAttachments: boolean;
  isRead: boolean;
  preview: string;
  messageId: string;
  size: number;
  isSigned: boolean;
  isEncrypted: boolean;
}

export interface EmailListResponse {
  total: number;
  page: number;
  pageSize: number;
  emails: EmailSummary[];
  hasMore: boolean;
}

export interface AttachmentInfo {
  filename: string;
  contentType: string;
  size: number;
  partId: string;
}

export interface GpgEmailInfo {
  isSigned: boolean;
  isEncrypted: boolean;
  signatureStatus?: string | null;
  signerFingerprint?: string | null;
  signerKeyId?: string | null;
  signerUid?: string | null;
  decrypted: boolean;
  encryptionKeyIds?: string[];
}

export interface EmailDetail {
  uid: string;
  mailbox: string;
  fromAddress: string;
  toAddresses: string[];
  subject: string;
  date: string | null;
  hasAttachments: boolean;
  isRead: boolean;
  preview: string;
  messageId: string;
  size: number;
  isSigned: boolean;
  isEncrypted: boolean;
  htmlBody: string | null;
  textBody: string | null;
  ccAddresses: string[];
  bccAddresses: string[];
  rawHeaders: Record<string, string>;
  attachments: AttachmentInfo[];
  gpg?: GpgEmailInfo | null;
}

export interface EmailQueryParams {
  mailbox: string;
  folder?: string;
}

export interface InjectEmailParams {
  mailbox: string;
  from: string;
  to: string[];
  subject: string;
  htmlBody?: string;
  textBody?: string;
  date?: string;
  headers?: Record<string, string>;
  sign?: boolean;
  encrypt?: boolean;
  replyTo?: string;
  inReplyTo?: string;
  references?: string[];
  cc?: string[];
  returnPath?: string;
  realisticHeaders?: boolean;
}

export interface InjectResult {
  uid: string;
  mailbox: string;
}

export interface BulkInjectResponse {
  injected: number;
  failed: number;
  ids: string[];
}

export interface MailboxCreateParams {
  username: string;
  password: string;
  domain?: string;
  displayName?: string;
}

export interface Mailbox {
  id: string;
  address: string;
  username: string;
  displayName: string;
  domain: string;
  isActive: boolean;
  createdAt: string;
  quotaMb: number;
  emailCount: number;
  unreadCount: number;
}

export interface MailboxListResponse {
  mailboxes: Mailbox[];
  total: number;
}

export interface FolderInfo {
  name: string;
  messageCount: number;
  unseenCount: number;
}

export interface MailboxStats {
  mailboxId: string;
  address: string;
  totalEmails: number;
  unreadEmails: number;
  totalSizeBytes: number;
  folders: FolderInfo[];
}

export interface DomainCreateParams {
  name: string;
  dkimSelector?: string;
}

export interface DnsRecordInfo {
  recordType: string;
  hostname: string;
  expectedValue: string;
  verified: boolean;
  currentValue: string | null;
  purpose: string;
}

export interface Domain {
  id: number;
  name: string;
  isActive: boolean;
  createdAt: string;
  dkimSelector: string;
  mxVerified: boolean;
  spfVerified: boolean;
  dkimVerified: boolean;
  dmarcVerified: boolean;
  mtaStsVerified: boolean;
  tlsRptVerified: boolean;
  lastDnsCheck: string | null;
  allVerified: boolean;
}

export interface DomainDetail extends Domain {
  dnsRecords: DnsRecordInfo[];
  dkimPublicKeyTxt?: string | null;
}

export interface DomainListResponse {
  domains: Domain[];
  total: number;
}

export interface DnsCheckResponse {
  mxVerified: boolean;
  spfVerified: boolean;
  dkimVerified: boolean;
  dmarcVerified: boolean;
  mtaStsVerified: boolean;
  tlsRptVerified: boolean;
  allVerified: boolean;
  dnsRecords: DnsRecordInfo[];
}

export interface AliasCreateParams {
  sourceAddress: string;
  destinationAddress: string;
}

export interface AliasUpdateParams {
  destinationAddress?: string;
  enabled?: boolean;
}

export interface Alias {
  id: number;
  sourceAddress: string;
  destinationAddress: string;
  domain: string;
  isCatchall: boolean;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface AliasListResponse {
  aliases: Alias[];
  total: number;
}

export interface GpgGenerateParams {
  mailboxAddress: string;
  name?: string;
  algorithm?: 'RSA' | 'ECC';
  keyLength?: number;
  expire?: string;
}

export interface GpgImportParams {
  armoredKey: string;
  mailboxAddress?: string;
}

export interface GpgKey {
  id: string;
  mailboxAddress: string;
  fingerprint: string;
  keyId: string;
  uidName?: string | null;
  uidEmail?: string | null;
  algorithm?: string | null;
  keyLength?: number | null;
  createdAt: string;
  expiresAt?: string | null;
  isPrivate: boolean;
  isActive: boolean;
}

export interface GpgKeyListResponse {
  keys: GpgKey[];
  total: number;
}

export interface GpgPublishResult {
  published: boolean;
  keyFingerprint: string;
  message: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  createdAt: string;
  lastUsedAt: string | null;
  isActive: boolean;
}

export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export interface ApiKeyCreateParams {
  name: string;
}

export interface HealthResponse {
  status: string;
  [key: string]: unknown;
}

export interface CertificateStatus {
  configured: boolean;
  commonName?: string | null;
  sanDnsNames: string[];
  notBefore?: string | null;
  notAfter?: string | null;
  fingerprintSha256?: string | null;
  uploadedAt?: string | null;
}

export type EventType =
  | 'email.received'
  | 'email.sent'
  | 'email.deleted'
  | 'mailbox.created'
  | 'mailbox.deleted'
  | 'heartbeat';

export interface MailcueEvent<T = unknown> {
  type: EventType | string;
  data: T;
  id?: string;
  retry?: number;
}

export interface BulkInjectParams {
  emails: InjectEmailParams[];
}
