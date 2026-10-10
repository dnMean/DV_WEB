import { Module } from '@nestjs/common';

import { grpcProviders } from './outbox.provider';
import { PaymentsController, PaymentsGrpcController } from './payments.controller';
import { PaymentsService } from './payments.service';
import { Dependencies } from './policy';
import { PrismaService } from './prisma.service';

@Module({
  controllers: [PaymentsController, PaymentsGrpcController],
  providers: [PrismaService, ...grpcProviders, Dependencies, PaymentsService],
})
export class AppModule {}
