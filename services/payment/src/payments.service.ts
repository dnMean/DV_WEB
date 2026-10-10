import { Injectable } from '@nestjs/common';
import { Prisma, Refund } from '@prisma/client';

import { AppError, CurrentUser, Outbox, isStaff, isSystem, log } from './common';
import { EligibilityOut, PaymentOut, RefundCheckOut, RefundIn, RefundOut, RefundResultOut } from './dto';
import { PrismaService } from './prisma.service';
import { Dependencies, PaymentWithRefunds, evaluate, refundableOf, refundedOf, withRefunds } from './policy';

const vnd = (v: number) => `${String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}đ`;

const refundOut = (r: Refund): RefundOut => ({
  id: r.id, order_id: r.orderId, amount: r.amount, reason: r.reason, status: r.status, created_at: r.createdAt.toISOString(),
});

export function paymentOut(p: PaymentWithRefunds): PaymentOut {
  return {
    id: p.id, order_id: p.orderId, user_id: p.userId, amount: p.amount, method: p.method, status: p.status,
    refunded_amount: refundedOf(p), refundable_amount: refundableOf(p), refunds: p.refunds.map(refundOut),
    created_at: p.createdAt.toISOString(),
  };
}

@Injectable()
export class PaymentsService {
  constructor(private readonly db: PrismaService, private readonly deps: Dependencies, private readonly outbox: Outbox) {}

  async get(orderId: number, user: CurrentUser): Promise<PaymentOut> {
    const payment = await this.db.payment.findUnique({ where: { orderId }, include: withRefunds });
    if (!payment) throw new AppError(404, 'payment_not_found', `Đơn ${orderId} chưa có thanh toán nào`);
    if (!isStaff(user) && payment.userId !== user.id) {
      throw new AppError(403, 'forbidden', 'Bạn không có quyền xem thanh toán của đơn hàng này');
    }
    return paymentOut(payment);
  }

  async eligibility(orderId: number, user: CurrentUser): Promise<EligibilityOut> {
    try {
      const check = await evaluate(this.db, this.deps, user, orderId, null);
      const message = check.beforeShipping
        ? `Đơn đã thanh toán nhưng chưa giao: chỉ có thể hoàn toàn bộ ${vnd(check.refundable)}, `
          + 'đơn sẽ bị huỷ khi yêu cầu được duyệt.'
        : `Đơn đã giao: có thể hoàn một phần hoặc toàn bộ, tối đa ${vnd(check.refundable)}.`;
      return {
        order_id: orderId, eligible: true, reason: 'ok', message: `${message} Cần nhân viên duyệt.`,
        max_refundable: check.refundable, full_refund_required: check.beforeShipping,
      };
    } catch (exc) {
      if (!(exc instanceof AppError) || exc.status !== 409) throw exc; // 403/404/503 stay errors
      return {
        order_id: orderId, eligible: false, reason: exc.error, message: exc.message, max_refundable: 0,
        full_refund_required: false,
      };
    }
  }

  async validate(body: RefundIn, user: CurrentUser): Promise<RefundCheckOut> {
    const check = await evaluate(this.db, this.deps, user, body.order_id, body.amount);
    return {
      eligible: true, order_status: check.order.status, refundable_amount: check.refundable,
      full_refund_required: check.beforeShipping,
    };
  }

  private async replay(key: string, body: RefundIn): Promise<RefundResultOut | null> {
    const existing = await this.db.refund.findUnique({ where: { idempotencyKey: key }, include: { payment: { include: withRefunds } } });
    if (!existing) return null;
    if (existing.orderId !== body.order_id || existing.amount !== body.amount) {
      throw new AppError(409, 'idempotency_key_conflict', 'Idempotency-Key đã dùng cho một yêu cầu khác');
    }
    return { refund: refundOut(existing), replayed: true, refundable_amount: refundableOf(existing.payment) };
  }

  /** Executes an approved refund (system token from the Gateway) or a staff refund. Idempotent per key. */
  async refund(body: RefundIn, user: CurrentUser, key: string | undefined): Promise<RefundResultOut> {
    if (!key) throw new AppError(400, 'idempotency_key_required', 'Thiếu header Idempotency-Key');
    if (key.length > 128) throw new AppError(422, 'validation_error', 'Idempotency-Key: tối đa 128 ký tự');
    const replayed = await this.replay(key, body);
    if (replayed) return replayed;

    let result: { refund: Refund; payment: PaymentWithRefunds };
    try {
      result = await this.db.$transaction(async (tx) => {
        // rules are re-checked at execution time: the order may have changed since the ticket was created
        const check = await evaluate(tx, this.deps, user, body.order_id, body.amount, true);
        // stop the parcel first; if it already left, no money moves
        if (check.beforeShipping) await this.deps.cancelShipment(body.order_id, key);
        const p = check.payment;
        const refund = await tx.refund.create({
          data: {
            paymentId: p.id, orderId: p.orderId, userId: p.userId, amount: body.amount, reason: body.reason,
            idempotencyKey: key, requestedBy: isSystem(user) ? user.onBehalfOf! : user.id, requestedRole: user.role,
          },
        });
        const refunded = refundedOf(p) + body.amount;
        const full = refunded >= p.amount;
        const payment = await tx.payment.update({
          where: { id: p.id }, data: { status: full ? 'REFUNDED' : 'PARTIALLY_REFUNDED' }, include: withRefunds,
        });
        await this.outbox.add(tx, 'order', 'RefundApplied', { order_id: p.orderId, total_refunded: refunded, full },
          `order-${p.orderId}-refunded-${refunded}`);
        return { refund, payment };
      }, { timeout: 20_000 });
    } catch (exc) {
      if (exc instanceof Prisma.PrismaClientKnownRequestError && exc.code === 'P2002') { // same key committed concurrently
        const again = await this.replay(key, body);
        if (again) return again;
      }
      throw exc;
    }
    await this.outbox.flush();
    log.info(`refund ${result.refund.id} created: order=${result.refund.orderId} amount=${result.refund.amount} by ${user.role}`);
    return { refund: refundOut(result.refund), replayed: false, refundable_amount: refundableOf(result.payment) };
  }

  /** gRPC Charge (Order): simulated payment, always succeeds; one payment per order. */
  async charge(req: { order_id: number; user_id: number; amount: number; method: string }) {
    if (!(req.order_id > 0) || !(req.user_id > 0) || !(req.amount > 0) || !req.method || req.method.length > 30) {
      throw new AppError(422, 'validation_error', 'order_id, user_id, amount > 0 và method là bắt buộc');
    }
    let existing = await this.db.payment.findUnique({ where: { orderId: req.order_id } });
    if (!existing) {
      try {
        existing = await this.db.payment.create({
          data: { orderId: req.order_id, userId: req.user_id, amount: req.amount, method: req.method, status: 'SUCCESS' },
        });
        log.info(`payment for order ${req.order_id}: ${req.amount} via ${req.method}`);
      } catch (exc) {
        if (!(exc instanceof Prisma.PrismaClientKnownRequestError && exc.code === 'P2002')) throw exc;
        existing = await this.db.payment.findUniqueOrThrow({ where: { orderId: req.order_id } }); // charged concurrently
      }
    }
    if (existing.userId !== req.user_id || existing.amount !== req.amount) {
      throw new AppError(409, 'payment_conflict', `Đơn ${req.order_id} đã có thanh toán với dữ liệu khác`);
    }
    return {
      id: existing.id, order_id: existing.orderId, user_id: existing.userId, amount: existing.amount,
      method: existing.method, status: existing.status, created_at: existing.createdAt.toISOString(),
    };
  }
}
