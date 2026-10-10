/** One-line JSON logs (ts, service, level, request_id, msg) and X-Request-ID propagation. */
import { AsyncLocalStorage } from 'node:async_hooks';
import { randomUUID } from 'node:crypto';

export const REQUEST_ID_HEADER = 'x-request-id';

const context = new AsyncLocalStorage<{ requestId: string }>();
const LEVELS = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 } as const;
type Level = keyof typeof LEVELS;

let serviceName = process.env.SERVICE_NAME ?? 'service';
const minLevel = LEVELS[(process.env.LOG_LEVEL?.toUpperCase() as Level) ?? 'INFO'] ?? LEVELS.INFO;

export function setServiceName(name: string): void {
  serviceName = name;
}

export function getRequestId(): string {
  return context.getStore()?.requestId ?? '-';
}

/** Run `fn` with a request id (the incoming one, or a new one) visible to logs and outgoing calls. */
export function runWithRequestId<T>(requestId: string | undefined, fn: () => T): T {
  return context.run({ requestId: requestId || randomUUID().replace(/-/g, '') }, fn);
}

/** Headers to attach when calling another service over HTTP. */
export function forwardHeaders(): Record<string, string> {
  const rid = getRequestId();
  return rid === '-' ? {} : { 'X-Request-ID': rid };
}

function write(level: Level, msg: string, err?: unknown): void {
  if (LEVELS[level] < minLevel) return;
  const entry: Record<string, unknown> = {
    ts: new Date().toISOString(),
    service: serviceName,
    level,
    request_id: getRequestId(),
    msg,
  };
  if (err instanceof Error && err.stack) entry.exc = err.stack;
  process.stdout.write(JSON.stringify(entry) + '\n');
}

export const log = {
  debug: (msg: string) => write('DEBUG', msg),
  info: (msg: string) => write('INFO', msg),
  warn: (msg: string, err?: unknown) => write('WARNING', msg, err),
  error: (msg: string, err?: unknown) => write('ERROR', msg, err),
};
