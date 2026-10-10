/**
 * Transactional outbox for service-to-service updates (docs/USECASES.md section 4).
 *
 * A service writes an outbox row in the same DB transaction as its own change, then delivers it as a gRPC call:
 * right away after commit (`flush()`), and again from a background timer while the target is down.
 * Targets must be idempotent (every row carries a stable idempotency key).
 *
 * Works with any Prisma client whose schema has the `OutboxMessage` model (table `outbox`).
 */
import { GrpcClient, RpcCallError } from './grpc';
import { log } from './logging';

export const PENDING = 'PENDING';
export const DONE = 'DONE';
export const FAILED = 'FAILED';

interface OutboxRow {
  id: number;
  target: string;
  method: string;
  payload: unknown;
  idempotencyKey: string;
  attempts: number;
}

// Prisma model delegate (typed loosely so each service's generated client fits)
interface OutboxDelegate {
  create(args: { data: Record<string, unknown> }): Promise<unknown>;
  findMany(args: Record<string, unknown>): Promise<OutboxRow[]>;
  update(args: { where: { id: number }; data: Record<string, unknown> }): Promise<unknown>;
  groupBy(args: Record<string, unknown>): Promise<Array<{ status: string; _count: { _all: number } }>>;
}
type HasOutbox = { outboxMessage: OutboxDelegate };

export class Outbox {
  private running: Promise<number> | null = null;
  private timer: NodeJS.Timeout | null = null;
  private readonly db: HasOutbox;

  constructor(
    prisma: { outboxMessage: unknown },
    private readonly targets: Record<string, GrpcClient>,
    private readonly maxAttempts = 8,
  ) {
    this.db = prisma as HasOutbox;
  }

  /** Queue a call; pass the transaction client so it commits together with the caller's change. */
  async add(tx: unknown, target: string, method: string, payload: object, key: string): Promise<void> {
    if (!(target in this.targets)) throw new Error(`unknown outbox target ${target}`);
    await (tx as HasOutbox).outboxMessage.create({ data: { target, method, payload, idempotencyKey: key } });
  }

  /** Deliver every due message. Concurrent calls share one run. */
  flush(): Promise<number> {
    if (!this.running) {
      this.running = this.deliverDue().finally(() => {
        this.running = null;
      });
    }
    return this.running;
  }

  private async deliverDue(): Promise<number> {
    const rows = await this.db.outboxMessage.findMany({
      where: { status: PENDING, nextAttemptAt: { lte: new Date() } },
      orderBy: { id: 'asc' },
      take: 50,
    });
    for (const row of rows) await this.deliver(row);
    return rows.length;
  }

  private async deliver(row: OutboxRow): Promise<void> {
    const attempts = row.attempts + 1;
    try {
      await this.targets[row.target].call(row.method, row.payload as object, { idempotencyKey: row.idempotencyKey });
      await this.db.outboxMessage.update({ where: { id: row.id }, data: { attempts, status: DONE, lastError: null } });
      return;
    } catch (exc) {
      const err = exc instanceof RpcCallError ? exc : null;
      const message = err ? `${err.status} ${err.error}: ${err.message}` : String(exc);
      if (err && !err.retryable) {
        // the target rejected it; retrying will not help
        log.error(`outbox #${row.id} ${row.target}.${row.method} rejected: ${message}`);
        await this.db.outboxMessage.update({
          where: { id: row.id },
          data: { attempts, status: FAILED, lastError: message.slice(0, 300) },
        });
        return;
      }
      if (attempts >= this.maxAttempts) {
        log.error(`outbox #${row.id} ${row.target}.${row.method} gave up: ${message}`);
        await this.db.outboxMessage.update({ where: { id: row.id }, data: { attempts, status: FAILED, lastError: message } });
        return;
      }
      const delayMs = Math.min(2 ** attempts, 60) * 1000;
      log.warn(`outbox #${row.id} ${row.target}.${row.method} failed (${message}), retry #${attempts}`);
      await this.db.outboxMessage.update({
        where: { id: row.id },
        data: { attempts, lastError: message, nextAttemptAt: new Date(Date.now() + delayMs) },
      });
    }
  }

  async stats(): Promise<Record<string, number>> {
    const rows = await this.db.outboxMessage.groupBy({ by: ['status'], _count: { _all: true } });
    return Object.fromEntries(rows.map((r) => [r.status, r._count._all]));
  }

  start(intervalMs: number): void {
    if (intervalMs <= 0) return;
    this.timer = setInterval(() => {
      this.flush().catch((exc) => log.error('outbox flush failed', exc));
    }, intervalMs);
    this.timer.unref();
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
  }
}
