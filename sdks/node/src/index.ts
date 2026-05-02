export { Mailcue, VERSION, type MailcueOptions } from './client.js';
export {
  MailcueError,
  AuthenticationError,
  AuthorizationError,
  NotFoundError,
  ConflictError,
  ValidationError,
  RateLimitError,
  ServerError,
  NetworkError,
  TimeoutError,
} from './errors.js';
export type { ErrorContext, RateLimitContext } from './errors.js';
export type { FetchLike } from './transport.js';
export type { StreamOptions } from './events.js';
export * from './types.js';
