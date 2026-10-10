/** Refund rules (docs/USECASES.md section 2), evaluated against live Order and Shipping state over gRPC. */
import { Inject, Injectable } from '@nestjs/common';
import { Payment, Prisma, Refund } from '@prisma/client';

import { AppError, CurrentUser, GrpcClient, RpcCallError, isStaff, isSystem, log } from './common';
import { ORDER, SHIPPING } from './outbox.provider';

export type PaymentWithRefunds = Payment & { refunds: Refund[] };
export const withRefunds = { refunds: { orderBy: { id: 'asc' } } } satisfies Prisma.PaymentInclude;

export const refundedOf = (p: PaymentWithRefunds) => p.refunds.reduce((s, r) => s + r.amount, 0);
export const refundableOf = (p: PaymentWithRefunds) => p.amount - refundedOf(p);
const vnd = (v: number) => `${String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}đ`;

interface OrderView {
  id: number;
  user_id: number;
  status: string;
}

export interface RefundCheck {
  payment: PaymentWithRefunds;
  order: OrderView;
  beforeShipping: boolean; // PAID and still in the warehouse: refund = cancel the order
  full: boolean;
  refundable: number;
}

const unavailable = (what: string) => new AppError(503, 'dependency_unavailable', what);

@Injectable()
export class Dependencies {
  constructor(@Inject(ORDER) private readonly orderRpc: GrpcClient, @Inject(SHIPPING) private readonly shippingRpc: GrpcClient) {}

  async order(orderId: number): Promise<OrderView> {
    try {
      return await this.orderRpc.call<OrderView>('GetOrder', { order_id: orderId });
    } catch (exc) {
      if (exc instanceof RpcCallError && exc.status === 404) {
        throw new AppError(404, 'order_not_found', `Không tìm thấy đơn hàng ${orderId}`);
      }
      log.error(`GetOrder ${orderId} failed: ${String(exc)}`);
      throw unavailable(exc instanceof RpcCallError && exc.error === 'dependency_unavailable'
        ? 'Hệ thống đơn hàng/vận chuyển tạm thời không phản hồi' : 'Không đọc được đơn hàng');
    }
  }

  async shipment(orderId: number): Promise<{ status: string } | null> {
    try {
      return await this.shippingRpc.call<{ status: string }>('GetShipment', { order_id: orderId });
    } catch (exc) {
      if (exc instanceof RpcCallError && exc.status === 404) return null;
      log.error(`GetShipment ${orderId} failed: ${String(exc)}`);
      throw unavailable('Không đọc được vận đơn');
    }
  }

  async cancelShipment(orderId: number, key: string): Promise<void> {
    try {
      await this.shippingRpc.call('CancelShipment', { order_id: orderId, idempotency_key: key }, { idempotencyKey: key });
    } catch (exc) {
      if (exc instanceof RpcCallError && exc.status === 404) return;
      if (exc instanceof RpcCallError && exc.status === 409) {
        throw new AppError(409, 'order_in_transit',
          'Hàng đã được giao cho đơn vị vận chuyển nên không thể hoàn tiền lúc này. '
          + 'Khách vui lòng nhận hàng rồi yêu cầu hoàn/đổi trả.');
      }
      log.error(`CancelShipment ${orderId} failed: ${String(exc)}`);
      throw unavailable('Không huỷ được vận đơn');
    }
  }
}

/** Whether `user` may refund `amount` (null: just asking) on the order now. Throws the reason otherwise. */
export async function evaluate(
  tx: Prisma.TransactionClient, deps: Dependencies, user: CurrentUser, orderId: number, amount: number | null,
  lock = false,
): Promise<RefundCheck> {
  const order = await deps.order(orderId);

  // ownership first, so a stranger learns nothing about the order's state
  if (isSystem(user)) {
    if (user.onBehalfOf === null) throw new AppError(400, 'bad_request', 'System token cần header X-On-Behalf-Of');
    if (order.user_id !== user.onBehalfOf) throw new AppError(403, 'forbidden', 'Đơn hàng không thuộc về người yêu cầu hoàn tiền');
  } else if (!isStaff(user) && order.user_id !== user.id) {
    throw new AppError(403, 'forbidden', 'Bạn không có quyền yêu cầu hoàn tiền cho đơn hàng này');
  }

  if (lock) await tx.$queryRaw`SELECT id FROM payments WHERE order_id = ${orderId} FOR UPDATE`;
  const payment = await tx.payment.findUnique({ where: { orderId }, include: withRefunds });
  const { status } = order;
  if (status === 'PENDING' || !payment) {
    throw new AppError(409, 'order_not_paid', `Đơn ${orderId} chưa thanh toán nên không có gì để hoàn`);
  }
  if (status === 'SHIPPING') {
    throw new AppError(409, 'order_in_transit',
      `Đơn ${orderId} đang được giao. Khách vui lòng nhận hàng rồi yêu cầu hoàn/đổi trả.`);
  }
  const refundable = refundableOf(payment);
  if (status === 'CANCELLED' || status === 'REFUNDED' || refundable <= 0) {
    throw new AppError(409, 'order_not_refundable', `Đơn ${orderId} đã được hoàn tiền hoặc đã huỷ`);
  }
  if (amount !== null && amount > refundable) {
    throw new AppError(422, 'amount_exceeds_refundable',
      `Số tiền hoàn ${vnd(amount)} vượt quá số còn có thể hoàn (${vnd(refundable)})`, { refundable_amount: refundable });
  }

  const beforeShipping = status === 'PAID';
  if (beforeShipping) {
    const shipment = await deps.shipment(orderId);
    if (shipment && !['WAITING_PICKUP', 'CANCELLED'].includes(shipment.status)) {
      throw new AppError(409, 'order_in_transit',
        `Đơn ${orderId} đã được giao cho đơn vị vận chuyển. Khách vui lòng nhận hàng rồi yêu cầu hoàn.`);
    }
    if (amount !== null && amount !== refundable) {
      throw new AppError(422, 'full_refund_required',
        `Đơn ${orderId} chưa giao: chỉ có thể hoàn toàn bộ ${vnd(refundable)} (tương đương huỷ đơn)`,
        { refundable_amount: refundable });
    }
  }
  return { payment, order, beforeShipping, full: amount === null || amount === refundable, refundable };
}
