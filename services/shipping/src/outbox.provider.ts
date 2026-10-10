import { GrpcClient, Outbox, env } from './common';
import { PrismaService } from './prisma.service';

export const outboxProvider = {
  provide: Outbox,
  inject: [PrismaService],
  useFactory: (db: PrismaService) =>
    new Outbox(db, { order: new GrpcClient('order', 'OrderInternal', env('ORDER_GRPC', 'order:50051')) }),
};
