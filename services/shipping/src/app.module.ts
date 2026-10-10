import { Module } from '@nestjs/common';

import { outboxProvider } from './outbox.provider';
import { PrismaService } from './prisma.service';
import { ShippingController, ShippingGrpcController } from './shipping.controller';
import { ShippingService } from './shipping.service';

@Module({
  controllers: [ShippingController, ShippingGrpcController],
  providers: [PrismaService, outboxProvider, ShippingService],
})
export class AppModule {}
