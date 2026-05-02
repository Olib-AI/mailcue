export interface ErrorContext {
  status?: number;
  code?: string;
  requestId?: string;
  body?: unknown;
}

export class MailcueError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly requestId?: string;
  readonly body?: unknown;

  constructor(message: string, ctx: ErrorContext = {}) {
    super(message);
    this.name = 'MailcueError';
    if (ctx.status !== undefined) this.status = ctx.status;
    if (ctx.code !== undefined) this.code = ctx.code;
    if (ctx.requestId !== undefined) this.requestId = ctx.requestId;
    if (ctx.body !== undefined) this.body = ctx.body;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class AuthenticationError extends MailcueError {
  constructor(message = 'Authentication failed', ctx: ErrorContext = {}) {
    super(message, ctx);
    this.name = 'AuthenticationError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class AuthorizationError extends AuthenticationError {
  constructor(message = 'Forbidden', ctx: ErrorContext = {}) {
    super(message, ctx);
    this.name = 'AuthorizationError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class NotFoundError extends MailcueError {
  constructor(message = 'Not found', ctx: ErrorContext = {}) {
    super(message, ctx);
    this.name = 'NotFoundError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class ConflictError extends MailcueError {
  constructor(message = 'Conflict', ctx: ErrorContext = {}) {
    super(message, ctx);
    this.name = 'ConflictError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class ValidationError extends MailcueError {
  constructor(message = 'Validation failed', ctx: ErrorContext = {}) {
    super(message, ctx);
    this.name = 'ValidationError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export interface RateLimitContext extends ErrorContext {
  retryAfter?: number;
}

export class RateLimitError extends MailcueError {
  readonly retryAfter?: number;

  constructor(message = 'Rate limit exceeded', ctx: RateLimitContext = {}) {
    super(message, ctx);
    this.name = 'RateLimitError';
    if (ctx.retryAfter !== undefined) this.retryAfter = ctx.retryAfter;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class ServerError extends MailcueError {
  constructor(message = 'Server error', ctx: ErrorContext = {}) {
    super(message, ctx);
    this.name = 'ServerError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class NetworkError extends MailcueError {
  readonly cause?: unknown;

  constructor(message = 'Network error', cause?: unknown) {
    super(message, {});
    this.name = 'NetworkError';
    this.cause = cause;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class TimeoutError extends MailcueError {
  readonly timeoutMs?: number;

  constructor(message = 'Request timed out', timeoutMs?: number) {
    super(message, {});
    this.name = 'TimeoutError';
    if (timeoutMs !== undefined) this.timeoutMs = timeoutMs;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}
