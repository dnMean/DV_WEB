import { daysAgo, demoData, log } from './common';
import { PrismaService } from './prisma.service';

const RECIPIENTS: Record<number, [string, string, string]> = {
  1: ['Nguyễn Thị Alice', '0901234567', '25 Trần Hưng Đạo, Hoàn Kiếm, Hà Nội'],
  2: ['Trần Văn Bob', '0912345678', '8 Nguyễn Văn Linh, Hải Châu, Đà Nẵng'],
};

type Seed = [number, number, string, string, demoData.DemoEvent[]]; // order_id, user_id, status, tracking, events

const SHIPMENTS: Seed[] = [
  [1001, 1, 'DELIVERED', 'GHN1001VN', [
    ['WAITING_PICKUP', 'Kho TP.HCM', 'Đã tạo vận đơn, chờ lấy hàng', 10],
    ['IN_TRANSIT', 'Kho TP.HCM', 'Đã lấy hàng', 9],
    ['IN_TRANSIT', 'Kho Hà Nội', 'Đã đến kho giao hàng', 7],
    ['DELIVERED', 'Hoàn Kiếm, Hà Nội', 'Giao hàng thành công', 6],
  ]],
  [1002, 1, 'IN_TRANSIT', 'GHN1002VN', [
    ['IN_TRANSIT', 'Kho TP.HCM', 'Đã lấy hàng', 3],
    ['IN_TRANSIT', 'Kho trung chuyển Đà Nẵng', 'Đã đến kho trung chuyển', 2],
    ['IN_TRANSIT', 'Đà Nẵng', 'Đang vận chuyển đến kho Hà Nội', 1],
  ]],
  [1003, 1, 'WAITING_PICKUP', 'GHN1003VN', [['WAITING_PICKUP', 'Kho TP.HCM', 'Đã tạo vận đơn, chờ lấy hàng', 0]]],
  [1005, 2, 'WAITING_PICKUP', 'GHN1005VN', [['WAITING_PICKUP', 'Kho TP.HCM', 'Đã tạo vận đơn, chờ lấy hàng', 0]]],
];

/** Hand-written shipments + shipments of generated demo orders (default DEMO_EXTRA_ORDERS). */
export async function seed(db: PrismaService, extra?: number): Promise<void> {
  if (await db.shipment.findFirst({ select: { id: true } })) return;
  const all = [...SHIPMENTS];
  for (const o of demoData.generate(extra)) {
    if (o.shipmentStatus) all.push([o.id, o.userId, o.shipmentStatus, o.trackingCode, o.shipmentEvents]);
  }
  await db.$transaction(async (tx) => {
    for (const [i, [orderId, userId, status, trackingCode, events]] of all.entries()) {
      const [recipientName, recipientPhone, address] = RECIPIENTS[userId];
      await tx.shipment.create({
        data: {
          id: i + 1, orderId, userId, status, carrier: 'GHN', trackingCode, recipientName, recipientPhone, address,
          events: {
            create: events.map(([s, location, description, days]) => ({ status: s, location, description, occurredAt: daysAgo(days) })),
          },
        },
      });
    }
  }, { timeout: 60_000 });
  await db.$queryRawUnsafe(
    "SELECT setval(pg_get_serial_sequence('shipments', 'id'), (SELECT COALESCE(MAX(id), 1) FROM shipments))");
  log.info(`seeded ${all.length} shipments`);
}

export async function reset(db: PrismaService, extra: number): Promise<void> {
  await db.$executeRawUnsafe('TRUNCATE shipments, shipment_events, outbox RESTART IDENTITY CASCADE');
  await seed(db, extra);
}
