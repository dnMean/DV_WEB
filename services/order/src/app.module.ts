import { Module } from '@nestjs/common';

import { CheckoutService } from './checkout.service';
import { Dependencies } from './deps';
import { OrdersController, OrdersGrpcController } from './orders.controller';
import { OrdersService } from './orders.service';
import { grpcProviders } from './outbox.provider';
import { PrismaService } from './prisma.service';

@Module({
  controllers: [OrdersController, OrdersGrpcController],
  providers: [PrismaService, ...grpcProviders, Dependencies, OrdersService, CheckoutService],
})
export class AppModule {}
