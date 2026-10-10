import { Module } from '@nestjs/common';

import { PrismaService } from './prisma.service';
import { ProductController } from './product.controller';
import { ProductGrpcController } from './product.grpc';
import { ProductService } from './product.service';

@Module({
  controllers: [ProductController, ProductGrpcController],
  providers: [PrismaService, ProductService],
})
export class AppModule {}
