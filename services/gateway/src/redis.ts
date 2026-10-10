/**
 * Redis state shared by every Gateway instance:
 * - token bucket per (user, tool) for rate limiting;
 * - idempotency lock so an identical write call is never forwarded twice at the same time.
 */
import Redis from 'ioredis';

import { log } from './common/logging';

const PREFIX = 'gw:';

// KEYS[1] bucket; ARGV: capacity, refill per ms. Uses the Redis clock so all gateways agree.
const TOKEN_BUCKET = `
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1]) or capacity
local ts = tonumber(data[2]) or now
tokens = math.min(capacity, tokens + (now - ts) * rate)
local allowed = 0
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry = (1 - tokens) / rate
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate) + 1000)
return {allowed, tostring(retry)}
`;

// delete the lock only if we still own it
const RELEASE = `if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end`;

export class GatewayState {
  readonly redis: Redis;

  constructor(url: string) {
    this.redis = new Redis(url, { maxRetriesPerRequest: 2, enableOfflineQueue: true, lazyConnect: false });
    this.redis.on('error', (err) => log.warn(`redis: ${err.message}`));
  }

  /** Returns [allowed, retryAfterSeconds]. */
  async allow(userId: number, tool: string, perMinute: number): Promise<[boolean, number]> {
    const [allowed, retryMs] = (await this.redis.eval(
      TOKEN_BUCKET, 1, `${PREFIX}rl:${userId}:${tool}`, perMinute, perMinute / 60_000,
    )) as [number, string];
    return [allowed === 1, Number(retryMs) / 1000];
  }

  /** Try to take the lock for an idempotency key; returns a release function, or null if already held. */
  async lock(key: string, ttlMs: number): Promise<(() => Promise<void>) | null> {
    const token = `${process.pid}-${Date.now()}-${Math.random()}`;
    const ok = await this.redis.set(`${PREFIX}idem:${key}`, token, 'PX', ttlMs, 'NX');
    if (ok !== 'OK') return null;
    return async () => {
      await this.redis.eval(RELEASE, 1, `${PREFIX}idem:${key}`, token).catch((exc: Error) =>
        log.warn(`cannot release idempotency lock: ${exc.message}`));
    };
  }

  /** Dev reset: forget every bucket and lock. */
  async reset(): Promise<void> {
    let cursor = '0';
    do {
      const [next, keys] = await this.redis.scan(cursor, 'MATCH', `${PREFIX}*`, 'COUNT', 500);
      if (keys.length) await this.redis.del(...keys);
      cursor = next;
    } while (cursor !== '0');
  }
}
