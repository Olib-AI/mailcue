export { Mailcue, VERSION, type MailcueOptions } from './client.js';
export {
  MailcueError,
  AuthenticationError,
  AuthorizationError,
  PermissionError,
  NotFoundError,
  ConflictError,
  ValidationError,
  RateLimitError,
  ServerError,
  NetworkError,
  TimeoutError,
} from './errors.js';
export type { ErrorContext, PermissionContext, RateLimitContext } from './errors.js';
export type { FetchLike } from './transport.js';
export type { StreamOptions } from './events.js';
export * from './types.js';
