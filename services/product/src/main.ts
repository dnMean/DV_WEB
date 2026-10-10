import { AppModule } from './app.module';
import { bootstrap } from './common/nest';
import { PrismaService } from './prisma.service';
import { seed } from './seed';

void bootstrap({
  name: 'product',
  title: 'OpsPilot Product Service',
  module: AppModule,
  grpc: 'product',
  beforeListen: (app) => seed(app.get(PrismaService)),
});
