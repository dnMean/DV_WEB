import { GrpcClient, Outbox, env } from './common';
import { PrismaService } from './prisma.service';

export const PRODUCT = 'PRODUCT_GRPC';
export const PAYMENT = 'PAYMENT_GRPC';
export const SHIPPING = 'SHIPPING_GRPC';

/** gRPC clients of the services Order depends on (one channel each, shared by direct calls and the outbox). */
export const grpcProviders = [
  { provide: PRODUCT, useFactory: () => new GrpcClient('product', 'ProductInternal', env(PRODUCT, 'product:50051')) },
  { provide: PAYMENT, useFactory: () => new GrpcClient('payment', 'PaymentInternal', env(PAYMENT, 'payment:50051')) },
  { provide: SHIPPING, useFactory: () => new GrpcClient('shipping', 'ShippingInternal', env(SHIPPING, 'shipping:50051')) },
  {
    provide: Outbox,
    inject: [PrismaService, PRODUCT, SHIPPING],
    useFactory: (db: PrismaService, product: GrpcClient, shipping: GrpcClient) => new Outbox(db, { product, shipping }),
  },
];
