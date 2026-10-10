import { daysAgo, demoData, log } from './common';
import { PrismaService } from './prisma.service';

// One SUCCESS payment per order with status >= PAID (see the order seed). [id, order_id, user_id, amount, method]
const PAYMENTS: Array<[number, number, number, number, string]> = [
  [1, 1001, 1, 350_000, 'COD'],
  [2, 1002, 1, 1_200_000, 'CARD'],
  [3, 1003, 1, 2_500_000, 'BANK_TRANSFER'],
  [4, 1005, 2, 800_000, 'E_WALLET'],
];

/** Hand-written payments + payments/refunds of generated demo orders (default DEMO_EXTRA_ORDERS). */
export async function seed(db: PrismaService, extra?: number): Promise<void> {
  if (await db.payment.findFirst({ select: { id: true } })) return;
  const payments = PAYMENTS.map(([id, orderId, userId, amount, method]) => ({
    id, orderId, userId, amount, method, status: 'SUCCESS', createdAt: new Date(),
  }));
  const refunds = [];
  for (const o of demoData.generate(extra)) {
    if (o.paymentMethod === null) continue;
    const id = payments.length + 1;
    const paidAt = daysAgo(o.daysAgo, o.id % 24);
    const status = o.refundedAmount === 0 ? 'SUCCESS' : o.refundedAmount === o.total ? 'REFUNDED' : 'PARTIALLY_REFUNDED';
    payments.push({ id, orderId: o.id, userId: o.userId, amount: o.total, method: o.paymentMethod, status, createdAt: paidAt });
    if (o.refundedAmount) {
      refunds.push({
        paymentId: id, orderId: o.id, userId: o.userId, amount: o.refundedAmount, reason: o.refundReason ?? '',
        idempotencyKey: `seed-${o.id}`, requestedBy: o.userId, requestedRole: 'system',
        createdAt: new Date(paidAt.getTime() + Math.min(2, o.daysAgo) * 86_400_000),
      });
    }
  }
  await db.$transaction([db.payment.createMany({ data: payments }), db.refund.createMany({ data: refunds })]);
  await db.$queryRawUnsafe(
    "SELECT setval(pg_get_serial_sequence('payments', 'id'), (SELECT COALESCE(MAX(id), 1) FROM payments))");
  log.info(`seeded ${payments.length} payments`);
}

export async function reset(db: PrismaService, extra: number): Promise<void> {
  await db.$executeRawUnsafe('TRUNCATE payments, refunds, outbox RESTART IDENTITY CASCADE');
  await seed(db, extra);
}
