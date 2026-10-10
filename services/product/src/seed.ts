import { log } from './common';
import { PrismaService } from './prisma.service';
import { normalize } from './text';

// [id, sku, name, category, description, price, stock] — ids/prices referenced by the order seed and demo data.
const PRODUCTS: Array<[number, string, string, string, string, number, number]> = [
  [1, 'PHN-SS-A15', 'Điện thoại Samsung Galaxy A15', 'Điện thoại',
    'Màn hình 6.5 inch, RAM 8GB, bộ nhớ 128GB, pin 5000mAh.', 2_500_000, 12],
  [2, 'HP-SONY-CH520', 'Tai nghe Bluetooth Sony WH-CH520', 'Tai nghe',
    'Tai nghe chụp tai không dây, pin 50 giờ, sạc nhanh.', 1_200_000, 20],
  [3, 'CHG-ANKER-20W', 'Sạc nhanh Anker 20W USB-C', 'Sạc',
    'Củ sạc nhanh PD 20W cho iPhone và Android.', 350_000, 45],
  [4, 'CBL-BASEUS-C1M', 'Cáp sạc USB-C Baseus 1m', 'Phụ kiện',
    'Cáp USB-C sang USB-C, hỗ trợ sạc nhanh 60W.', 150_000, 80],
  [5, 'CASE-IP15-SIL', 'Ốp lưng silicon iPhone 15', 'Phụ kiện',
    'Ốp lưng silicon mềm, chống sốc, nhiều màu.', 200_000, 35],
  [6, 'GLS-IP15', 'Kính cường lực iPhone 15', 'Phụ kiện',
    'Kính cường lực 9H, chống vân tay.', 100_000, 60],
  [7, 'WR-XM-BAND8', 'Vòng đeo tay Xiaomi Smart Band 8', 'Đồng hồ thông minh',
    'Theo dõi sức khoẻ, đo nhịp tim, pin 16 ngày.', 800_000, 18],
  [8, 'PB-XM-10K', 'Sạc dự phòng Xiaomi 10000mAh', 'Sạc',
    'Pin sạc dự phòng 10000mAh, sạc nhanh 22.5W.', 400_000, 0],
];

export async function seed(db: PrismaService): Promise<void> {
  if (await db.product.findFirst({ select: { id: true } })) return;
  await db.product.createMany({
    data: PRODUCTS.map(([id, sku, name, category, description, price, stock]) => ({
      id, sku, name, category, description, price, stock,
      searchText: normalize(`${name} ${category} ${description}`),
    })),
  });
  await db.$queryRawUnsafe(
    "SELECT setval(pg_get_serial_sequence('products', 'id'), (SELECT COALESCE(MAX(id), 1) FROM products))");
  log.info(`seeded ${PRODUCTS.length} products`);
}

export async function reset(db: PrismaService): Promise<void> {
  await db.$executeRawUnsafe('TRUNCATE products, restock_log RESTART IDENTITY CASCADE');
  await seed(db);
}
