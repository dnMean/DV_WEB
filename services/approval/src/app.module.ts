import { Module } from '@nestjs/common';

import { PrismaService } from './prisma.service';
import { ApprovalGrpcController, RefundRequestsController, TicketsController } from './tickets.controller';
import { TicketsService } from './tickets.service';

@Module({
  controllers: [TicketsController, RefundRequestsController, ApprovalGrpcController],
  providers: [PrismaService, TicketsService],
})
export class AppModule {}
