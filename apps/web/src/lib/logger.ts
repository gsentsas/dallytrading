/**
 * Structured logging with correlation ids (§56).
 *
 * One id follows a request from the browser through this backend into Odoo and
 * back, so an incident can be reconstructed instead of guessed at. Odoo returns
 * its own `request_id`, which is logged alongside ours.
 *
 * Secrets are never logged. The redaction list below is applied to every payload,
 * because the alternative — remembering to strip fields at each call site — fails
 * exactly once and then it is in the log forever.
 */

/** Keys whose values are replaced before anything is written. */
const REDACTED_KEYS = new Set([
  'apikey',
  'api_key',
  'authorization',
  'password',
  'passwd',
  'secret',
  'token',
  'x-api-key',
  'cookie',
  'set-cookie',
]);

const MAX_STRING_LENGTH = 2000;

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogContext {
  readonly correlationId?: string;
  readonly [key: string]: unknown;
}

/** Recursively strip secrets and cap oversized strings. */
export function redact(value: unknown, depth = 0): unknown {
  if (depth > 6) {
    return '[max depth]';
  }
  if (typeof value === 'string') {
    return value.length > MAX_STRING_LENGTH
      ? `${value.slice(0, MAX_STRING_LENGTH)}… [truncated]`
      : value;
  }
  if (value === null || typeof value !== 'object') {
    return value;
  }
  if (Array.isArray(value)) {
    return value.slice(0, 50).map((item) => redact(item, depth + 1));
  }

  const output: Record<string, unknown> = {};
  for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
    output[key] = REDACTED_KEYS.has(key.toLowerCase())
      ? '[redacted]'
      : redact(nested, depth + 1);
  }
  return output;
}

function emit(level: LogLevel, message: string, context: LogContext = {}): void {
  const entry = {
    timestamp: new Date().toISOString(),
    level,
    message,
    ...(redact(context) as Record<string, unknown>),
  };

  // JSON on one line: greppable, and parseable by any log shipper without a
  // custom pattern.
  const line = JSON.stringify(entry);

  if (level === 'error') {
    console.error(line);
  } else if (level === 'warn') {
    console.warn(line);
  } else {
    console.log(line);
  }
}

export const logger = {
  debug: (message: string, context?: LogContext) => {
    if (process.env.NODE_ENV !== 'production') {
      emit('debug', message, context);
    }
  },
  info: (message: string, context?: LogContext) => emit('info', message, context),
  warn: (message: string, context?: LogContext) => emit('warn', message, context),
  error: (message: string, context?: LogContext) => emit('error', message, context),
};

/**
 * Generate a correlation id.
 *
 * `crypto.randomUUID` is available in Node 20 and in every browser we support.
 */
export function newCorrelationId(): string {
  return crypto.randomUUID();
}
