import { Injectable } from '@nestjs/common';
import { Prisma, Product } from '@prisma/client';

import { AppError, log } from './common';
import { ProductOut, StockOut } from './dto';
import { PrismaService } from './prisma.service';
import { normalize } from './text';

export interface StockItem {
  product_id: number;
  qty: number;
}

const catalogItem = (p: Product) => ({ id: p.id, name: p.name, price: p.price, stock: p.stock });
const isUniqueViolation = (e: unknown) => e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002';

@Injectable()
export class ProductService {
  constructor(private readonly db: PrismaService) {}

  static toOut(p: Product): ProductOut {
    return {
      id: p.id, sku: p.sku, name: p.name, category: p.category, description: p.description, price: p.price,
      in_stock: p.stock > 0,
    };
  }

  async search(q: string, limit: number): Promise<ProductOut[]> {
    const words = normalize(q).split(/\s+/).filter(Boolean);
    const rows = await this.db.product.findMany({
      where: { AND: words.map((w) => ({ searchText: { contains: w } })) },
      orderBy: { id: 'asc' },
      take: limit,
    });
    return rows.map(ProductService.toOut);
  }

  async get(id: number): Promise<Product> {
    const product = await this.db.product.findUnique({ where: { id } });
    if (!product) throw new AppError(404, 'product_not_found', `Không tìm thấy sản phẩm ${id}`);
    return product;
  }

  async stock(id: number): Promise<StockOut> {
    const p = await this.get(id);
    return { product_id: p.id, name: p.name, stock: p.stock, in_stock: p.stock > 0 };
  }

  // --- internal (gRPC, called by Order) ---------------------------------------------------------

  async catalog(ids: number[]) {
    const rows = await this.db.product.findMany({ where: { id: { in: ids } }, orderBy: { id: 'asc' } });
    return rows.map(catalogItem);
  }

  /** Lock the rows of every requested product (SELECT ... FOR UPDATE); 422 if one does not exist. */
  private async locked(tx: Prisma.TransactionClient, items: StockItem[]): Promise<Map<number, Product>> {
    const ids = [...new Set(items.map((i) => i.product_id))];
    await tx.$queryRaw`SELECT id FROM products WHERE id IN (${Prisma.join(ids)}) FOR UPDATE`;
    const products = new Map((await tx.product.findMany({ where: { id: { in: ids } } })).map((p) => [p.id, p]));
    const missing = ids.filter((id) => !products.has(id));
    if (missing.length) throw new AppError(422, 'product_not_found', `Không có sản phẩm [${missing.join(', ')}]`);
    return products;
  }

  private static checkItems(items: StockItem[], key: string | undefined): asserts key is string {
    if (!key) throw new AppError(400, 'idempotency_key_required', 'Thiếu idempotency key');
    if (!items.length || items.some((i) => !(i.qty > 0) || !(i.product_id > 0))) {
      throw new AppError(422, 'validation_error', 'items: cần ít nhất một sản phẩm, qty > 0');
    }
  }

  /** Put items back in stock when an order is cancelled/refunded before shipping. Idempotent per key. */
  async restock(items: StockItem[], reason: string, key: string | undefined): Promise<{ replayed: boolean }> {
    ProductService.checkItems(items, key);
    if (await this.db.restockLog.findUnique({ where: { idempotencyKey: key } })) return { replayed: true };
    try {
      await this.db.$transaction(async (tx) => {
        await this.locked(tx, items);
        for (const item of items) {
          await tx.product.update({ where: { id: item.product_id }, data: { stock: { increment: item.qty } } });
        }
        await tx.restockLog.create({ data: { idempotencyKey: key, reason: reason.slice(0, 200) } });
      });
    } catch (exc) {
      if (isUniqueViolation(exc)) return { replayed: true }; // same key processed concurrently
      throw exc;
    }
    log.info(`restocked ${JSON.stringify(items.map((i) => [i.product_id, i.qty]))} (${reason})`);
    return { replayed: false };
  }

  /** Take every item out of stock when an order is placed, or nothing (409 out_of_stock). Idempotent per key. */
  async reserve(items: StockItem[], reason: string, key: string | undefined) {
    ProductService.checkItems(items, key);
    const ids = [...new Set(items.map((i) => i.product_id))];
    const replay = async () => ({ replayed: true, items: await this.catalog(ids) });
    if (await this.db.restockLog.findUnique({ where: { idempotencyKey: key } })) return replay();

    const wanted = new Map<number, number>();
    for (const item of items) wanted.set(item.product_id, (wanted.get(item.product_id) ?? 0) + item.qty);
    try {
      const updated = await this.db.$transaction(async (tx) => {
        const products = await this.locked(tx, items);
        const short = [...wanted].filter(([pid, qty]) => products.get(pid)!.stock < qty).map(([pid, qty]) => ({
          product_id: pid, name: products.get(pid)!.name, requested: qty, available: products.get(pid)!.stock,
        }));
        if (short.length) {
          const names = short.map((s) => `${s.name} (còn ${s.available})`).join(', ');
          throw new AppError(409, 'out_of_stock', `Không đủ hàng: ${names}`, { items: short });
        }
        const out: Product[] = [];
        for (const [pid, qty] of wanted) {
          out.push(await tx.product.update({ where: { id: pid }, data: { stock: { decrement: qty } } }));
        }
        await tx.restockLog.create({ data: { idempotencyKey: key, reason: reason.slice(0, 200) } });
        return out;
      });
      log.info(`reserved ${JSON.stringify([...wanted])} (${reason})`);
      return { replayed: false, items: updated.map(catalogItem) };
    } catch (exc) {
      if (isUniqueViolation(exc)) return replay(); // same key processed concurrently
      throw exc;
    }
  }
}
