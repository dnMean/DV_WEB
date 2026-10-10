import { AppModule } from './app.module';
import { bootstrap } from './common/nest';
import { PrismaService } from './prisma.service';
import { seed } from './seed';

void bootstrap({
  name: 'approval',
  title: 'OpsPilot Approval Service',
  module: AppModule,
  grpc: 'approval',
  beforeListen: (app) => seed(app.get(PrismaService)),
});
