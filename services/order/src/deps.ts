/** Synchronous gRPC calls to Product and Payment used while ordering (docs/USECASES.md section 3b). */
import { Inject, Injectable } from '@nestjs/common';

import { AppError, GrpcClient, RpcCallError, log } from './common';
import { PAYMENT, PRODUCT } from './outbox.provider';

export interface CatalogItem {
  id: number;
  name: string;
  price: number;
  stock: number;
}

export interface StockItem {
  product_id: number;
  qty: number;
}

export interface ChargeResult {
  amount: number;
  method: string;
  status: string;
}

/** 404/409/422 from the dependency are business answers for the customer; anything else is a 503. */
function asAppError(exc: unknown): AppError {
  if (exc instanceof RpcCallError) {
    if ([404, 409, 422].includes(exc.status)) {
      return new AppError(exc.status === 409 ? 409 : 422, exc.error, exc.message, exc.extra);
    }
    log.error(`dependency call failed: ${exc.status} ${exc.error} ${exc.message}`);
    return new AppError(503, 'dependency_unavailable', exc.error === 'dependency_unavailable'
      ? 'Hệ thống kho/thanh toán tạm thời không phản hồi'
      : 'Hệ thống kho/thanh toán trả lỗi không mong đợi');
  }
  return exc instanceof AppError ? exc : new AppError(503, 'dependency_unavailable', 'Lỗi khi gọi service phụ thuộc');
}

@Injectable()
export class Dependencies {
  constructor(@Inject(PRODUCT) private readonly product: GrpcClient, @Inject(PAYMENT) private readonly payment: GrpcClient) {}

  async catalog(productIds: number[]): Promise<Map<number, CatalogItem>> {
    try {
      const reply = await this.product.call<{ items: CatalogItem[] }>('GetCatalog', { ids: productIds });
      return new Map(reply.items.map((p) => [p.id, p]));
    } catch (exc) {
      throw asAppError(exc);
    }
  }

  /** Take every item out of stock, or nothing (409 out_of_stock). */
  async reserve(items: StockItem[], key: string, reason: string): Promise<void> {
    try {
      await this.product.call('Reserve', { items, reason, idempotency_key: key });
    } catch (exc) {
      throw asAppError(exc);
    }
  }

  /** Best-effort undo of `reserve` when the order could not be saved. */
  async release(items: StockItem[], key: string, reason: string): Promise<void> {
    try {
      await this.product.call('Restock', { items, reason, idempotency_key: key });
    } catch {
      log.error(`could not release reservation ${key}: stock must be fixed by hand`);
    }
  }

  async charge(orderId: number, userId: number, amount: number, method: string): Promise<ChargeResult> {
    try {
      return await this.payment.call<ChargeResult>('Charge', { order_id: orderId, user_id: userId, amount, method });
    } catch (exc) {
      throw asAppError(exc);
    }
  }
}
