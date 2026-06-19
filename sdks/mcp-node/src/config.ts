/**
 * Configuration is read entirely from the environment so the server can be
 * dropped into any MCP client config block without code changes.
 *
 *   MAILCUE_BASE_URL      MailCue server URL (default http://localhost:8088)
 *   MAILCUE_API_KEY       X-API-Key credential (mc_...)
 *   MAILCUE_BEARER_TOKEN  JWT alternative to MAILCUE_API_KEY
 *   MAILCUE_MAILBOX       optional. When set, the agent is locked to this one
 *                         mailbox: every tool operates on it, the `mailbox`
 *                         argument disappears, and cross-mailbox tools are not
 *                         registered at all.
 */

const DEFAULT_BASE_URL = 'http://localhost:8088';

export interface McpConfig {
  baseUrl: string;
  apiKey?: string;
  bearerToken?: string;
  /** When set, the server runs in single-mailbox (locked) mode. */
  mailbox?: string;
}

export class ConfigError extends Error {}

function clean(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  const trimmed = value.trim();
  return trimmed === '' ? undefined : trimmed;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): McpConfig {
  const apiKey = clean(env['MAILCUE_API_KEY']);
  const bearerToken = clean(env['MAILCUE_BEARER_TOKEN']);

  if (!apiKey && !bearerToken) {
    throw new ConfigError(
      'Missing credentials: set MAILCUE_API_KEY (preferred) or MAILCUE_BEARER_TOKEN.',
    );
  }

  const config: McpConfig = {
    baseUrl: clean(env['MAILCUE_BASE_URL']) ?? DEFAULT_BASE_URL,
  };
  if (apiKey) config.apiKey = apiKey;
  if (bearerToken) config.bearerToken = bearerToken;

  const mailbox = clean(env['MAILCUE_MAILBOX']);
  if (mailbox) config.mailbox = mailbox;

  return config;
}

export function isLocked(config: McpConfig): config is McpConfig & { mailbox: string } {
  return typeof config.mailbox === 'string';
}
