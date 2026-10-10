import { Injectable } from '@nestjs/common';
import { Order, OrderItem, Prisma } from '@prisma/client';

import { AppError, CurrentUser, Outbox, isStaff, log } from './common';
import { OrderOut, OrderPage, OrderSummaryOut } from './dto';
import { PrismaService } from './prisma.service';

export type FullOrder = Order & { items: OrderItem[] };
export const withItems = { items: { orderBy: { id: 'asc' } } } satisfies Prisma.OrderInclude;
type Tx = Prisma.TransactionClient;

export function toOrderOut(o: FullOrder): OrderOut {
  return {
    id: o.id, user_id: o.userId, status: o.status, total: o.total, refunded_amount: o.refundedAmount,
    items: o.items.map((i) => ({ product_id: i.productId, name: i.name, qty: i.qty, price: i.price })),
    note: o.note, created_at: o.createdAt.toISOString(),
  };
}

function toSummary(o: FullOrder): OrderSummaryOut {
  return {
    id: o.id, user_id: o.userId, status: o.status, total: o.total, refunded_amount: o.refundedAmount,
    items: o.items.map((i) => `${i.name} x${i.qty}`).join(', '), created_at: o.createdAt.toISOString(),
  };
}

/** Lock an order row (SELECT ... FOR UPDATE) and load it, or 404. */
export async function lockOrder(tx: Tx, orderId: number): Promise<FullOrder> {
  await tx.$queryRaw`SELECT id FROM orders WHERE id = ${orderId} FOR UPDATE`;
  const order = await tx.order.findUnique({ where: { id: orderId }, include: withItems });
  if (!order) throw new AppError(404, 'order_not_found', `Không tìm thấy đơn hàng ${orderId}`);
  return order;
}

// shipment status -> {current order status: new order status}
const SHIPPING_TRANSITIONS: Record<string, Record<string, string>> = {
  IN_TRANSIT: { PAID: 'SHIPPING', SHIPPING: 'SHIPPING' },
  DELIVERED: { PAID: 'DELIVERED', SHIPPING: 'DELIVERED', DELIVERED: 'DELIVERED' },
};

@Injectable()
export class OrdersService {
  constructor(private readonly db: PrismaService, private readonly outbox: Outbox) {}

  private checkOwner(order: FullOrder, user: CurrentUser): void {
    if (!isStaff(user) && order.userId !== user.id) {
      throw new AppError(403, 'forbidden', 'Bạn không có quyền truy cập đơn hàng này');
    }
  }

  async page(where: Prisma.OrderWhereInput, limit: number, offset: number): Promise<OrderPage> {
    const [total, rows] = await Promise.all([
      this.db.order.count({ where }),
      this.db.order.findMany({ where, orderBy: { id: 'desc' }, take: limit, skip: offset, include: withItems }),
    ]);
    return { total, offset, limit, has_more: offset + rows.length < total, orders: rows.map(toSummary) };
  }

  async get(orderId: number, user?: CurrentUser): Promise<FullOrder> {
    const order = await this.db.order.findUnique({ where: { id: orderId }, include: withItems });
    if (!order) throw new AppError(404, 'order_not_found', `Không tìm thấy đơn hàng ${orderId}`);
    if (user) this.checkOwner(order, user);
    return order;
  }

  /** Put the order's items back in stock (once per order, whatever the retries). */
  private queueRestock(tx: Tx, order: FullOrder, reason: string) {
    const key = `order-${order.id}-restock`;
    return this.outbox.add(tx, 'product', 'Restock', {
      items: order.items.map((i) => ({ product_id: i.productId, qty: i.qty })),
      reason: `${reason} order ${order.id}`,
      idempotency_key: key,
    }, key);
  }

  async cancel(orderId: number, user: CurrentUser): Promise<FullOrder> {
    const order = await this.db.$transaction(async (tx) => {
      const o = await lockOrder(tx, orderId);
      this.checkOwner(o, user);
      if (o.status === 'CANCELLED') return o; // idempotent: cancelling twice is not an error
      if (o.status === 'PAID') {
        throw new AppError(409, 'order_already_paid',
          `Đơn ${orderId} đã thanh toán nên không thể huỷ trực tiếp. `
          + 'Hãy tạo yêu cầu hoàn tiền bằng refund_payment (cần nhân viên duyệt).',
          { suggested_tool: 'refund_payment' });
      }
      if (o.status !== 'PENDING') {
        throw new AppError(409, 'order_not_cancellable', `Đơn ${orderId} đang ở trạng thái ${o.status}, không thể huỷ.`);
      }
      await this.queueRestock(tx, o, 'cancel');
      log.info(`order ${orderId} cancelled by user ${user.id}`);
      return tx.order.update({ where: { id: orderId }, data: { status: 'CANCELLED' }, include: withItems });
    });
    await this.outbox.flush();
    return order;
  }

  // --- internal (gRPC): updates from Payment and Shipping, all idempotent ----------------------

  async refundApplied(orderId: number, totalRefunded: number, full: boolean): Promise<FullOrder> {
    const order = await this.db.$transaction(async (tx) => {
      const o = await lockOrder(tx, orderId);
      let status = o.status;
      if (full) {
        if (o.status === 'PAID') { // refunded before shipping: goods never left the warehouse
          status = 'REFUNDED';
          await this.queueRestock(tx, o, 'refund');
        } else if (o.status === 'DELIVERED') {
          status = 'REFUNDED';
        } else if (o.status !== 'REFUNDED') {
          throw new AppError(409, 'invalid_transition', `Không thể hoàn toàn bộ đơn ở trạng thái ${o.status}`);
        }
      } else if (!['DELIVERED', 'REFUNDED'].includes(o.status)) {
        throw new AppError(409, 'invalid_transition', `Không thể hoàn một phần đơn ở trạng thái ${o.status}`);
      }
      const refundedAmount = Math.max(o.refundedAmount, totalRefunded);
      log.info(`order ${orderId} refund applied: ${o.status} -> ${status}, refunded=${refundedAmount}`);
      return tx.order.update({ where: { id: orderId }, data: { status, refundedAmount }, include: withItems });
    });
    await this.outbox.flush();
    return order;
  }

  async shippingStatus(orderId: number, shipmentStatus: string): Promise<FullOrder> {
    if (!(shipmentStatus in SHIPPING_TRANSITIONS)) {
      throw new AppError(422, 'validation_error', 'status: phải là IN_TRANSIT hoặc DELIVERED');
    }
    return this.db.$transaction(async (tx) => {
      const o = await lockOrder(tx, orderId);
      const next = SHIPPING_TRANSITIONS[shipmentStatus][o.status];
      if (!next) throw new AppError(409, 'invalid_transition', `Đơn ${o.status} không thể chuyển theo vận đơn ${shipmentStatus}`);
      if (next === o.status) return o;
      log.info(`order ${orderId} ${o.status} -> ${next} (shipment ${shipmentStatus})`);
      return tx.order.update({ where: { id: orderId }, data: { status: next }, include: withItems });
    });
  }
}
