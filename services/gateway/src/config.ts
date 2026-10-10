import { env, envNumber } from './common/env';

export const config = {
  port: envNumber('PORT', 8000),
  serviceUrls: env('SERVICE_URLS', '').split(',').map((u) => u.trim().replace(/\/+$/, '')).filter(Boolean),
  approvalGrpc: env('APPROVAL_GRPC', 'approval:50051'),
  redisUrl: env('REDIS_URL', 'redis://redis:6379'),
  registryRefreshSeconds: envNumber('REGISTRY_REFRESH_SECONDS', 60),
  toolTimeoutMs: envNumber('TOOL_TIMEOUT_SECONDS', 5) * 1000,
  toolMaxResultChars: envNumber('TOOL_MAX_RESULT_CHARS', 4000),
  rateLimitReadPerMin: envNumber('RATE_LIMIT_READ_PER_MIN', 10),
  rateLimitWritePerMin: envNumber('RATE_LIMIT_WRITE_PER_MIN', 3),
  rateLimitStaffWritePerMin: envNumber('RATE_LIMIT_STAFF_WRITE_PER_MIN', 30), // staff process many orders in a row
  auditLogPath: env('AUDIT_LOG_PATH', '/data/audit.jsonl'),
};
