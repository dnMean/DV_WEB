import { AppModule } from './app.module';
import { bootstrap } from './common/nest';
import { PrismaService } from './prisma.service';
import { seed } from './seed';

void bootstrap({
  name: 'auth',
  title: 'OpsPilot Auth Service',
  module: AppModule,
  grpc: 'auth',
  beforeListen: (app) => seed(app.get(PrismaService)),
});
