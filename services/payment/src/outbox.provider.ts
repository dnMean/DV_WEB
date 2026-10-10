import { GrpcClient, Outbox, env } from './common';
import { PrismaService } from './prisma.service';

export const ORDER = 'ORDER_GRPC';
export const SHIPPING = 'SHIPPING_GRPC';

export const grpcProviders = [
  { provide: ORDER, useFactory: () => new GrpcClient('order', 'OrderInternal', env(ORDER, 'order:50051')) },
  { provide: SHIPPING, useFactory: () => new GrpcClient('shipping', 'ShippingInternal', env(SHIPPING, 'shipping:50051')) },
  {
    provide: Outbox,
    inject: [PrismaService, ORDER],
    useFactory: (db: PrismaService, order: GrpcClient) => new Outbox(db, { order }),
  },
];
