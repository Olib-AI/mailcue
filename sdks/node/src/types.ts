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

export interface WaitForEmailParams {
  mailbox: string;
  folder?: string;
  search?: string;
  subject?: string;
  from?: string;
  to?: string;
  minCount?: number;
  timeoutMs?: number;
  intervalMs?: number;
  pageSize?: number;
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

export type DeliverabilityStatus = 'pass' | 'warning' | 'fail' | 'info';
export type DeliverabilityCategoryId =
  | 'authentication'
  | 'content'
  | 'headers'
  | 'transport'
  | 'spam_filter'
  | 'attachments'
  | 'dns'
  | 'reputation'
  | 'links'
  | 'visual'
  | 'placement'
  | 'client_previews'
  | 'ai_analysis';

export interface DeliverabilityEvidence {
  code: string;
  title: string;
  value: string | number | boolean | null;
  score: number | null;
  description: string | null;
  recommendation: string | null;
}

export interface DeliverabilityCheck {
  id: string;
  category: DeliverabilityCategoryId;
  title: string;
  status: DeliverabilityStatus;
  summary: string;
  details: string[];
  evidence: DeliverabilityEvidence[];
  recommendation: string | null;
  points: number;
  maxPoints: number;
}

export interface DeliverabilityCategory {
  id: DeliverabilityCategoryId;
  title: string;
  score: number | null;
  points: number;
  maxPoints: number;
  checks: DeliverabilityCheck[];
}

export interface DeliverabilityReport {
  scoreVersion: string;
  reportId: string | null;
  rawSha256: string;
  cached: boolean;
  isBaseline: boolean;
  score: number;
  verdict: 'excellent' | 'good' | 'needs_work' | 'poor';
  summary: string;
  mailbox: string;
  uid: string;
  folder: string;
  messageId: string;
  senderDomain: string | null;
  generatedAt: string;
  categories: DeliverabilityCategory[];
  topRecommendations: string[];
  limitations: string[];
}

export type DeliverabilityRunCheck =
  | 'dns'
  | 'reputation'
  | 'links'
  | 'visual'
  | 'placement'
  | 'client_previews'
  | 'ai_analysis';

export interface DeliverabilityCapability {
  id: string;
  title: string;
  description: string;
  mode: 'local' | 'network' | 'provider';
  status: 'available' | 'disabled' | 'not_configured' | 'unavailable';
  reason: string | null;
}

export interface DeliverabilityRun {
  id: string;
  reportId: string;
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled';
  requestedChecks: DeliverabilityRunCheck[];
  capabilities: { capabilities: DeliverabilityCapability[] };
  categories: DeliverabilityCategory[];
  errorCode: string | null;
  errorDetail: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
}

export interface DeliverabilityReportSummary {
  id: string;
  mailbox: string;
  uid: string;
  folder: string;
  messageId: string;
  rawSha256: string;
  scoreVersion: string;
  score: number;
  verdict: string;
  isBaseline: boolean;
  createdAt: string;
}

export interface DeliverabilityReportList {
  reports: DeliverabilityReportSummary[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}

export interface DeliverabilityTrend {
  mailbox: string;
  points: Array<{ reportId: string; score: number; verdict: string; createdAt: string }>;
  count: number;
  averageScore: number | null;
  minimumScore: number | null;
  maximumScore: number | null;
  scoreDelta: number | null;
}

export interface DeliverabilityCheckChange {
  id: string;
  title: string;
  beforeStatus: string | null;
  afterStatus: string | null;
  beforePoints: number | null;
  afterPoints: number | null;
  pointsDelta: number;
}

export interface DeliverabilityComparison {
  beforeReportId: string;
  afterReportId: string;
  beforeScore: number;
  afterScore: number;
  scoreDelta: number;
  improved: number;
  regressed: number;
  unchanged: number;
  categories: Array<{
    id: string;
    title: string;
    beforeScore: number | null;
    afterScore: number | null;
    scoreDelta: number | null;
    checkChanges: DeliverabilityCheckChange[];
  }>;
}

export interface DeliverabilityPolicyParams {
  name: string;
  mailbox: string;
  enabled?: boolean;
  minimumScore?: number;
  maximumRegression?: number;
  failOnStatuses?: Array<'warning' | 'fail'>;
  requiredCheckIds?: string[];
  requiredCapabilities?: string[];
}

export interface DeliverabilityPolicy extends Required<DeliverabilityPolicyParams> {
  id: string;
  createdAt: string;
  updatedAt: string;
}

export interface DeliverabilityPolicyEvaluation {
  id: string;
  policyId: string;
  reportId: string;
  passed: boolean;
  score: number;
  scoreDelta: number | null;
  reasons: string[];
  createdAt: string;
}

export interface DeliverabilityProviderParams {
  name: string;
  kind: 'preview' | 'placement' | 'analysis';
  adapter: 'generic_http_preview' | 'seed_imap' | 'generic_http_analysis';
  enabled?: boolean;
  config: Record<string, string | number | boolean | string[]>;
  secret?: string | null;
}

export interface DeliverabilityProvider extends Omit<DeliverabilityProviderParams, 'secret'> {
  id: string;
  enabled: boolean;
  hasSecret: boolean;
  lastStatus: string;
  lastError: string | null;
  lastCheckedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface DeliverabilityScheduleParams {
  name: string;
  mailbox: string;
  enabled?: boolean;
  intervalMinutes?: number;
  checks?: DeliverabilityRunCheck[];
  policyId?: string | null;
}

export interface DeliverabilitySchedule extends Required<DeliverabilityScheduleParams> {
  id: string;
  nextRunAt: string | null;
  lastRunAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface DeliverabilityAlert {
  id: string;
  mailbox: string;
  reportId: string | null;
  runId: string | null;
  policyId: string | null;
  alertType: string;
  severity: string;
  title: string;
  detail: string;
  acknowledged: boolean;
  createdAt: string;
  acknowledgedAt: string | null;
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
  purpose?: 'standard' | 'deliverability';
}

export interface Mailbox {
  id: string;
  address: string;
  username: string;
  displayName: string;
  domain: string;
  isActive: boolean;
  purpose: 'standard' | 'deliverability';
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
  scopes: string[];
  allowedMailboxes: string[] | null;
}

export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export interface ApiKeyCreateParams {
  name: string;
  scopes?: string[];
  allowedMailboxes?: string[];
}

export interface ApiKeyUpdateParams {
  name?: string;
  scopes?: string[];
  allowedMailboxes?: string[];
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

export interface EmailValidationSyntax {
  isValid: boolean;
  localPart?: string | null;
  domain?: string | null;
  error?: string | null;
}

export interface EmailValidationDns {
  isValid: boolean;
  hasMx: boolean;
  hasNs: boolean;
  hasA: boolean;
  mxRecords: string[];
  nsRecords: string[];
  aRecords: string[];
  error?: string | null;
}

export interface EmailValidationMailbox {
  isValid: boolean | null;
  smtpCode?: number | null;
  smtpResponse?: string | null;
  catchAll?: boolean | null;
  error?: string | null;
}

export interface EmailValidationDisposable {
  isDisposable: boolean;
  error?: string | null;
}

export interface EmailValidationResponse {
  email: string;
  isValid: boolean;
  status: 'valid' | 'invalid' | 'undetermined' | 'disposable' | 'catch_all';
  syntax: EmailValidationSyntax;
  dns: EmailValidationDns;
  mailbox: EmailValidationMailbox;
  disposable: EmailValidationDisposable;
}
