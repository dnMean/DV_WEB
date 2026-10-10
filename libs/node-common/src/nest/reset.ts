import { envBool } from '../env';
import { AppError } from '../errors';
import { extraCount } from '../demo-data';

/**
 * POST /internal/reset[?extra_orders=N] (dev only): restore seed data (+N generated demo orders, default
 * DEMO_EXTRA_ORDERS). The route itself is @InternalOnly(); this checks ALLOW_RESET and the query.
 */
export function resetCount(extraOrders: string | undefined): number {
  if (!envBool('ALLOW_RESET', false)) throw new AppError(403, 'reset_disabled', 'ALLOW_RESET chưa bật');
  if (extraOrders === undefined || extraOrders === '') return extraCount();
  const n = Number(extraOrders);
  if (!Number.isInteger(n) || n < 0 || n > 1000) {
    throw new AppError(422, 'validation_error', 'extra_orders: phải là số nguyên 0–1000');
  }
  return n;
}
