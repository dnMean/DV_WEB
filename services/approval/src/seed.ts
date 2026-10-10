import { daysAgo, demoData, log } from './common';
import { PrismaService } from './prisma.service';
import { REFUND_TOOL, dedupKey } from './tickets.service';

const STAFF_ID = 3;

/** Refund tickets of generated demo orders (the hand-written orders 1001-1005 start without tickets). */
export async function seed(db: PrismaService, extra?: number): Promise<void> {
  if (await db.ticket.findFirst({ select: { id: true } })) return;
  const rows = demoData.generate(extra).flatMap((o) => o.tickets.map((t) => {
    const created = daysAgo(Math.max(o.daysAgo - 1, 0), o.id % 24);
    return {
      conversationId: '', userId: o.userId, tool: REFUND_TOOL,
      arguments: { order_id: o.id, amount: t.amount, reason: t.reason }, status: t.status,
      reviewerId: t.status === 'PENDING' ? null : STAFF_ID, reviewNote: t.reviewNote,
      result: t.status === 'EXECUTED' ? { status: 'ok', data: { seeded: true } } : undefined,
      dedupKey: dedupKey(o.userId, REFUND_TOOL, { order_id: o.id }), createdAt: created, updatedAt: created,
    };
  }));
  if (rows.length) {
    await db.ticket.createMany({ data: rows });
    log.info(`seeded ${rows.length} tickets`);
  }
}

export async function reset(db: PrismaService, extra: number): Promise<void> {
  await db.$executeRawUnsafe('TRUNCATE tickets');
  await seed(db, extra);
}
