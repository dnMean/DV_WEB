import { hash } from 'bcryptjs';

import { envNumber, log } from './common';
import { PrismaService } from './prisma.service';

const DEFAULT_PASSWORD = 'password123';

// [id, username, role, email, phone]
const USERS: Array<[number, string, string, string, string]> = [
  [1, 'alice', 'customer', 'alice@example.com', '0901234567'],
  [2, 'bob', 'customer', 'bob@example.com', '0912345678'],
  [3, 'staff1', 'staff', 'staff1@opspilot.local', '0987654321'],
];

export async function seed(db: PrismaService): Promise<void> {
  if (await db.user.findFirst({ select: { id: true } })) return;
  const passwordHash = await hash(DEFAULT_PASSWORD, envNumber('BCRYPT_ROUNDS', 12));
  await db.user.createMany({
    data: USERS.map(([id, username, role, email, phone]) => ({ id, username, role, email, phone, passwordHash })),
  });
  await db.$queryRawUnsafe(
    "SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT COALESCE(MAX(id), 1) FROM users))");
  log.info(`seeded ${USERS.length} users`);
}
