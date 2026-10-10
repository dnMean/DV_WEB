import { Injectable } from '@nestjs/common';
import { Prisma, Shipment, ShipmentEvent } from '@prisma/client';

import { AppError, CurrentUser, Outbox, isStaff, log } from './common';
import { AddressUpdateIn, AdvanceIn, ShipmentOut } from './dto';
import { PrismaService } from './prisma.service';

type WithEvents = Shipment & { events: ShipmentEvent[] };

const withEvents = { events: { orderBy: [{ occurredAt: 'asc' }, { id: 'asc' }] } } satisfies Prisma.ShipmentInclude;

// current status -> allowed next statuses (staff updates)
const ADVANCE: Record<string, string[]> = {
  WAITING_PICKUP: ['IN_TRANSIT'],
  IN_TRANSIT: ['IN_TRANSIT', 'DELIVERED'],
};

const notFound = (orderId: number) => new AppError(404, 'shipment_not_found', `Đơn ${orderId} chưa có vận đơn`);

@Injectable()
export class ShippingService {
  constructor(private readonly db: PrismaService, private readonly outbox: Outbox) {}

  static toOut(s: WithEvents): ShipmentOut {
    return {
      order_id: s.orderId, user_id: s.userId, status: s.status, carrier: s.carrier, tracking_code: s.trackingCode,
      recipient_name: s.recipientName, recipient_phone: s.recipientPhone, address: s.address,
      updated_at: s.updatedAt.toISOString(),
      events: s.events.map((e) => ({
        status: e.status, location: e.location, description: e.description, occurred_at: e.occurredAt.toISOString(),
      })),
    };
  }

  private async find(orderId: number, tx: Prisma.TransactionClient = this.db, lock = false): Promise<WithEvents> {
    if (lock) await tx.$queryRaw`SELECT id FROM shipments WHERE order_id = ${orderId} FOR UPDATE`;
    const shipment = await tx.shipment.findUnique({ where: { orderId }, include: withEvents });
    if (!shipment) throw notFound(orderId);
    return shipment;
  }

  private async owned(orderId: number, user: CurrentUser, tx?: Prisma.TransactionClient, lock = false) {
    const shipment = await this.find(orderId, tx, lock);
    if (!isStaff(user) && shipment.userId !== user.id) {
      throw new AppError(403, 'forbidden', 'Bạn không có quyền xem vận đơn của đơn hàng này');
    }
    return shipment;
  }

  async list(status: string | undefined, limit: number): Promise<ShipmentOut[]> {
    const rows = await this.db.shipment.findMany({
      where: status ? { status } : {}, orderBy: { orderId: 'desc' }, take: limit, include: withEvents,
    });
    return rows.map(ShippingService.toOut);
  }

  async get(orderId: number, user: CurrentUser): Promise<ShipmentOut> {
    return ShippingService.toOut(await this.owned(orderId, user));
  }

  async updateAddress(orderId: number, body: AddressUpdateIn, user: CurrentUser): Promise<ShipmentOut> {
    const out = await this.db.$transaction(async (tx) => {
      const s = await this.owned(orderId, user, tx, true);
      if (s.status !== 'WAITING_PICKUP') {
        throw new AppError(409, 'shipment_not_editable',
          `Vận đơn của đơn ${orderId} đang ở trạng thái ${s.status}, không thể đổi địa chỉ.`);
      }
      const name = body.recipient_name || s.recipientName;
      const phone = body.recipient_phone || s.recipientPhone;
      if (body.address === s.address && name === s.recipientName && phone === s.recipientPhone) return s; // idempotent
      await tx.shipmentEvent.create({
        data: { shipmentId: s.id, status: s.status, location: 'Hệ thống', description: 'Cập nhật địa chỉ giao hàng' },
      });
      return tx.shipment.update({
        where: { id: s.id }, data: { address: body.address, recipientName: name, recipientPhone: phone }, include: withEvents,
      });
    });
    log.info(`shipment for order ${orderId} address updated by user ${user.id}`);
    return ShippingService.toOut(out);
  }

  /** Staff: WAITING_PICKUP -> IN_TRANSIT -> DELIVERED; Order follows through the outbox. */
  async advance(orderId: number, body: AdvanceIn, user: CurrentUser): Promise<ShipmentOut> {
    const out = await this.db.$transaction(async (tx) => {
      const s = await this.find(orderId, tx, true);
      if (!(ADVANCE[s.status] ?? []).includes(body.status)) {
        throw new AppError(409, 'invalid_transition', `Không thể chuyển vận đơn từ ${s.status} sang ${body.status}`);
      }
      const changed = s.status !== body.status;
      const location = body.location || (s.status === 'WAITING_PICKUP' ? 'Kho TP.HCM'
        : body.status === 'DELIVERED' ? 'Địa chỉ người nhận' : 'Đang vận chuyển');
      const description = body.description || (body.status === 'DELIVERED' ? 'Giao hàng thành công'
        : changed ? 'Đã lấy hàng, đang vận chuyển' : `Đang vận chuyển qua ${location}`);
      await tx.shipmentEvent.create({ data: { shipmentId: s.id, status: body.status, location, description } });
      if (changed) {
        await this.outbox.add(tx, 'order', 'ShippingStatus', { order_id: orderId, status: body.status },
          `shipment-${orderId}-${body.status}`);
      }
      return tx.shipment.update({ where: { id: s.id }, data: { status: body.status }, include: withEvents });
    });
    await this.outbox.flush();
    log.info(`shipment ${orderId} -> ${body.status} by staff ${user.id}`);
    return ShippingService.toOut(out);
  }

  // --- internal (gRPC) ----------------------------------------------------------------------------

  /** Order: one shipment per order, a retried call returns the existing one. */
  async create(req: { order_id: number; user_id: number; recipient_name: string; recipient_phone: string; address: string }) {
    if (!(req.order_id > 0) || !(req.user_id > 0) || !req.recipient_name || !req.address) {
      throw new AppError(422, 'validation_error', 'order_id, user_id, recipient_name, address là bắt buộc');
    }
    const existing = await this.db.shipment.findUnique({ where: { orderId: req.order_id }, include: withEvents });
    if (existing) return ShippingService.toOut(existing);
    try {
      const created = await this.db.shipment.create({
        data: {
          orderId: req.order_id, userId: req.user_id, status: 'WAITING_PICKUP', carrier: 'GHN',
          trackingCode: `GHN${req.order_id}VN`, recipientName: req.recipient_name.slice(0, 100),
          recipientPhone: req.recipient_phone.slice(0, 20), address: req.address,
          events: { create: { status: 'WAITING_PICKUP', location: 'Kho TP.HCM', description: 'Đã tạo vận đơn, chờ lấy hàng' } },
        },
        include: withEvents,
      });
      log.info(`shipment created for order ${req.order_id}`);
      return ShippingService.toOut(created);
    } catch (exc) {
      if (exc instanceof Prisma.PrismaClientKnownRequestError && exc.code === 'P2002') { // created concurrently
        return ShippingService.toOut(await this.find(req.order_id));
      }
      throw exc;
    }
  }

  async getInternal(orderId: number) {
    return ShippingService.toOut(await this.find(orderId));
  }

  /** Payment (refund before shipping): cancel a shipment that has not left the warehouse. */
  async cancel(orderId: number) {
    const out = await this.db.$transaction(async (tx) => {
      const s = await this.find(orderId, tx, true);
      if (s.status === 'CANCELLED') return s;
      if (s.status !== 'WAITING_PICKUP') {
        throw new AppError(409, 'shipment_already_dispatched',
          `Vận đơn đơn ${orderId} đang ở trạng thái ${s.status}, không thể huỷ`);
      }
      await tx.shipmentEvent.create({
        data: { shipmentId: s.id, status: 'CANCELLED', location: 'Hệ thống', description: 'Huỷ vận đơn do đơn hàng được hoàn tiền' },
      });
      log.info(`shipment for order ${orderId} cancelled`);
      return tx.shipment.update({ where: { id: s.id }, data: { status: 'CANCELLED' }, include: withEvents });
    });
    return ShippingService.toOut(out);
  }
}
