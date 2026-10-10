import type { Metadata } from '@grpc/grpc-js';
import { Controller } from '@nestjs/common';
import { GrpcMethod } from '@nestjs/microservices';

import { handleRpc, idempotencyKeyOf } from './common/nest';
import { ProductService, StockItem } from './product.service';

interface StockRequest {
  items: StockItem[];
  reason: string;
  idempotency_key: string;
}

/** opspilot.product.ProductInternal (proto/product.proto), called by Order. */
@Controller()
export class ProductGrpcController {
  constructor(private readonly products: ProductService) {}

  @GrpcMethod('ProductInternal', 'GetCatalog')
  getCatalog(req: { ids: number[] }, md: Metadata) {
    return handleRpc(md, 'GetCatalog', async () => ({ items: await this.products.catalog(req.ids) }));
  }

  @GrpcMethod('ProductInternal', 'Reserve')
  reserve(req: StockRequest, md: Metadata) {
    return handleRpc(md, 'Reserve', () =>
      this.products.reserve(req.items, req.reason, idempotencyKeyOf(md, req.idempotency_key)));
  }

  @GrpcMethod('ProductInternal', 'Restock')
  restock(req: StockRequest, md: Metadata) {
    return handleRpc(md, 'Restock', () =>
      this.products.restock(req.items, req.reason, idempotencyKeyOf(md, req.idempotency_key)));
  }
}
