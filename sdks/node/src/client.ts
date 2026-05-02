import { MailcueError } from './errors.js';
import { Transport, type FetchLike } from './transport.js';
import { EventsClient } from './events.js';
import { EmailsResource } from './resources/emails.js';
import { MailboxesResource } from './resources/mailboxes.js';
import { DomainsResource } from './resources/domains.js';
import { AliasesResource } from './resources/aliases.js';
import { GpgResource } from './resources/gpg.js';
import { ApiKeysResource } from './resources/apiKeys.js';
import { SystemResource } from './resources/system.js';

const SDK_VERSION = '0.1.0';
const DEFAULT_BASE_URL = 'http://localhost:8088';
const DEFAULT_TIMEOUT_MS = 30000;
const DEFAULT_MAX_RETRIES = 3;

export interface MailcueOptions {
  apiKey?: string;
  bearerToken?: string;
  baseUrl?: string;
  timeout?: number;
  maxRetries?: number;
  fetch?: FetchLike;
  userAgent?: string;
}

export class Mailcue {
  readonly emails: EmailsResource;
  readonly mailboxes: MailboxesResource;
  readonly domains: DomainsResource;
  readonly aliases: AliasesResource;
  readonly gpg: GpgResource;
  readonly apiKeys: ApiKeysResource;
  readonly system: SystemResource;
  readonly events: EventsClient;

  private readonly transport: Transport;

  constructor(options: MailcueOptions = {}) {
    if (!options.apiKey && !options.bearerToken) {
      throw new MailcueError(
        'Mailcue requires either apiKey or bearerToken in the constructor options',
      );
    }

    const fetchImpl = options.fetch ?? (globalThis.fetch as FetchLike | undefined);
    if (!fetchImpl) {
      throw new MailcueError(
        'No fetch implementation found. Use Node 18+ or pass options.fetch.',
      );
    }

    this.transport = new Transport({
      baseUrl: options.baseUrl ?? DEFAULT_BASE_URL,
      auth: {
        ...(options.apiKey ? { apiKey: options.apiKey } : {}),
        ...(options.bearerToken ? { bearerToken: options.bearerToken } : {}),
      },
      timeout: options.timeout ?? DEFAULT_TIMEOUT_MS,
      maxRetries: options.maxRetries ?? DEFAULT_MAX_RETRIES,
      fetch: fetchImpl,
      userAgent: options.userAgent ?? `mailcue-node/${SDK_VERSION}`,
    });

    this.emails = new EmailsResource(this.transport);
    this.mailboxes = new MailboxesResource(this.transport);
    this.domains = new DomainsResource(this.transport);
    this.aliases = new AliasesResource(this.transport);
    this.gpg = new GpgResource(this.transport);
    this.apiKeys = new ApiKeysResource(this.transport);
    this.system = new SystemResource(this.transport);
    this.events = new EventsClient(this.transport);
  }
}

export const VERSION = SDK_VERSION;
