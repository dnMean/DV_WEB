/** Ordering by chat: quote -> place (customer types the quote code) -> pay (docs/USECASES.md section 3b). */
import { randomBytes, randomInt } from 'node:crypto';

import { Injectable } from '@nestjs/common';
import { Quote } from '@prisma/client';

import { AppError, CurrentUser, Outbox, envNumber, log } from './common';
import { Dependencies, StockItem } from './deps';
import { DeliveryOut, PaidOut, PayIn, PlacedOut, QuoteIn, QuoteOut } from './dto';
import { FullOrder, lockOrder, toOrderOut, withItems } from './orders.service';
import { PrismaService } from './prisma.service';

const CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'; // no 0/O, 1/I/L

interface QuoteLine {
  product_id: number;
  name: string;
  qty: number;
  price: number;
}

const money = (v: number) => `${String(v).replace(/\B(?=(\d{3})+(?!\d))/g, '.')}đ`; // 1.200.000đ

function quoteOut(q: Quote): QuoteOut {
  const minutes = Math.max(0, Math.floor((q.expiresAt.getTime() - Date.now()) / 60_000));
  const items = q.items as unknown as QuoteLine[];
  return {
    quote_id: q.id, total: q.total, recipient_name: q.recipientName, recipient_phone: q.recipientPhone,
    address: q.address, expires_in_minutes: minutes, order_id: q.orderId,
    items: items.map((i) => ({ ...i, subtotal: i.qty * i.price })),
    next_step: `Chưa đặt hàng. Trình bày báo giá cho khách; để đặt, khách phải tự gõ 'xác nhận ${q.id}' `
      + `trong ${minutes} phút.`,
  };
}

@Injectable()
export class CheckoutService {
  constructor(private readonly db: PrismaService, private readonly deps: Dependencies, private readonly outbox: Outbox) {}

  private async newCode(): Promise<string> {
    for (;;) {
      const code = Array.from({ length: 6 }, () => CODE_ALPHABET[randomInt(CODE_ALPHABET.length)]).join('');
      if (!(await this.db.quote.findUnique({ where: { id: code } }))) return code;
    }
  }

  async quote(body: QuoteIn, user: CurrentUser): Promise<QuoteOut> {
    const wanted = new Map<number, number>();
    for (const item of body.items) wanted.set(item.product_id, (wanted.get(item.product_id) ?? 0) + item.qty);
    const catalog = await this.deps.catalog([...wanted.keys()]);
    const missing = [...wanted.keys()].filter((pid) => !catalog.has(pid));
    if (missing.length) {
      throw new AppError(404, 'product_not_found', `Không có sản phẩm [${missing.join(', ')}]. Hãy tìm lại bằng search_products.`);
    }
    const short = [...wanted].filter(([pid, qty]) => catalog.get(pid)!.stock < qty).map(([pid, qty]) => ({
      product_id: pid, name: catalog.get(pid)!.name, requested: qty, available: catalog.get(pid)!.stock,
    }));
    if (short.length) {
      const names = short.map((s) => `${s.name} (còn ${s.available})`).join(', ');
      throw new AppError(409, 'out_of_stock', `Không đủ hàng: ${names}`, { items: short });
    }
    const items: QuoteLine[] = [...wanted].map(([pid, qty]) => ({
      product_id: pid, name: catalog.get(pid)!.name, qty, price: catalog.get(pid)!.price,
    }));
    const quote = await this.db.quote.create({
      data: {
        id: await this.newCode(), userId: user.id, items: items as object[], total: items.reduce((s, i) => s + i.qty * i.price, 0),
        recipientName: body.recipient_name, recipientPhone: body.recipient_phone, address: body.address,
        expiresAt: new Date(Date.now() + envNumber('QUOTE_TTL_MINUTES', 30) * 60_000),
      },
    });
    log.info(`quote ${quote.id} for user ${user.id}: ${quote.total}`);
    return quoteOut(quote);
  }

  private async placed(order: FullOrder): Promise<PlacedOut> {
    const d = await this.db.orderDelivery.findUnique({ where: { orderId: order.id } });
    return {
      order: toOrderOut(order),
      delivery: { recipient_name: d!.recipientName, recipient_phone: d!.recipientPhone, address: d!.address },
      next_step: `Đơn ${order.id} đang chờ thanh toán (${money(order.total)}). Để thanh toán, khách tự gõ mã đơn `
        + `và phương thức, vd 'thanh toán đơn ${order.id} bằng thẻ' (thẻ, chuyển khoản, ví điện tử; `
        + 'không hỗ trợ COD).',
    };
  }

  async place(quoteId: string, user: CurrentUser): Promise<PlacedOut> {
    const code = quoteId.toUpperCase();
    let reserved: { stock: StockItem[]; key: string; orderId: number } | null = null;
    let order: FullOrder;
    try {
      order = await this.db.$transaction(async (tx) => {
        await tx.$queryRaw`SELECT id FROM quotes WHERE id = ${code} FOR UPDATE`;
        const quote = await tx.quote.findUnique({ where: { id: code } });
        if (!quote || quote.userId !== user.id) throw new AppError(404, 'quote_not_found', `Không tìm thấy báo giá ${code}`);
        if (quote.orderId !== null) { // idempotent: confirming twice places one order
          return tx.order.findUniqueOrThrow({ where: { id: quote.orderId }, include: withItems });
        }
        if (quote.expiresAt < new Date()) {
          throw new AppError(409, 'quote_expired', `Báo giá ${code} đã hết hạn. Hãy tạo báo giá mới bằng quote_order.`);
        }
        const lines = quote.items as unknown as QuoteLine[];
        const created = await tx.order.create({
          data: {
            userId: user.id, status: 'PENDING', total: quote.total,
            items: { create: lines.map((i) => ({ productId: i.product_id, name: i.name, qty: i.qty, price: i.price })) },
            delivery: { create: { recipientName: quote.recipientName, recipientPhone: quote.recipientPhone, address: quote.address } },
          },
          include: withItems,
        });
        await tx.quote.update({ where: { id: code }, data: { orderId: created.id } });
        // a fresh key per attempt: a failed attempt releases exactly what it reserved
        const stock = lines.map((i) => ({ product_id: i.product_id, qty: i.qty }));
        const key = `quote-${code}-${randomBytes(4).toString('hex')}`;
        await this.deps.reserve(stock, key, `order ${created.id}`); // throws -> nothing is saved
        reserved = { stock, key, orderId: created.id };
        return created;
      }, { timeout: 20_000 });
    } catch (exc) {
      const r = reserved as { stock: StockItem[]; key: string; orderId: number } | null;
      if (r) await this.deps.release(r.stock, `${r.key}-release`, `order ${r.orderId} not saved`);
      throw exc;
    }
    log.info(`order ${order.id} placed from quote ${code} by user ${user.id}`);
    return this.placed(order);
  }

  async pay(orderId: number, body: PayIn, user: CurrentUser): Promise<PaidOut> {
    const result = await this.db.$transaction(async (tx) => {
      const o = await lockOrder(tx, orderId);
      if (o.userId !== user.id) throw new AppError(403, 'forbidden', 'Bạn không có quyền truy cập đơn hàng này');
      if (o.status !== 'PENDING') {
        if (o.status === 'CANCELLED') {
          throw new AppError(409, 'order_not_payable', `Đơn ${orderId} đã bị huỷ, không thể thanh toán.`);
        }
        throw new AppError(409, 'order_already_paid', `Đơn ${orderId} đã được thanh toán (trạng thái ${o.status}).`);
      }
      let d = await tx.orderDelivery.findUnique({ where: { orderId } });
      if (!d) {
        if (!body.recipient_name || !body.recipient_phone || !body.address) {
          throw new AppError(422, 'delivery_info_required',
            `Đơn ${orderId} chưa có thông tin giao hàng: cần tên người nhận, số điện thoại và địa chỉ.`);
        }
        d = await tx.orderDelivery.create({
          data: { orderId, recipientName: body.recipient_name, recipientPhone: body.recipient_phone, address: body.address },
        });
      }
      // money first (idempotent per order); the order only becomes PAID once Payment has recorded it
      const payment = await this.deps.charge(o.id, o.userId, o.total, body.method);
      const order = await tx.order.update({ where: { id: orderId }, data: { status: 'PAID' }, include: withItems });
      await this.outbox.add(tx, 'shipping', 'CreateShipment', {
        order_id: o.id, user_id: o.userId, recipient_name: d.recipientName, recipient_phone: d.recipientPhone,
        address: d.address,
      }, `order-${o.id}-shipment`);
      const delivery: DeliveryOut = { recipient_name: d.recipientName, recipient_phone: d.recipientPhone, address: d.address };
      return { order, payment, delivery };
    }, { timeout: 20_000 });
    await this.outbox.flush();
    log.info(`order ${orderId} paid by user ${user.id} via ${body.method}`);
    return {
      order: toOrderOut(result.order),
      payment: { amount: result.payment.amount, method: result.payment.method, status: result.payment.status },
      delivery: result.delivery,
      next_step: 'Đã thanh toán; vận đơn được tạo và chờ kho lấy hàng. Khách tra cứu bằng get_shipment.',
    };
  }
}
