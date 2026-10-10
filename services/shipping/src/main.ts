import { AppModule } from './app.module';
import { Outbox, envNumber } from './common';
import { bootstrap } from './common/nest';
import { PrismaService } from './prisma.service';
import { seed } from './seed';

void bootstrap({
  name: 'shipping',
  title: 'OpsPilot Shipping Service',
  module: AppModule,
  grpc: 'shipping',
  beforeListen: async (app) => {
    await seed(app.get(PrismaService));
    const outbox = app.get(Outbox);
    outbox.start(envNumber('OUTBOX_INTERVAL_SECONDS', 2) * 1000);
    await outbox.flush();
  },
});
