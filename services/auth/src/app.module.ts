import { Module } from '@nestjs/common';

import { AuthController, AuthGrpcController } from './auth.controller';
import { AuthService } from './auth.service';
import { PrismaService } from './prisma.service';

@Module({
  controllers: [AuthController, AuthGrpcController],
  providers: [PrismaService, AuthService],
})
export class AppModule {}
