import type { Metadata } from '@grpc/grpc-js';
import { RpcException } from '@nestjs/microservices';

import { INTERNAL_SECRET_HEADER, isInternalSecret } from '../auth';
import { AppError } from '../errors';
import { metadataValue, toGrpcError } from '../grpc';
import { REQUEST_ID_HEADER, log, runWithRequestId } from '../logging';

/**
 * Wraps a gRPC handler: checks the internal secret, carries the caller's request id into logs, and turns
 * AppError into a gRPC status the client decodes back (see ../grpc.ts).
 */
export function handleRpc<T>(md: Metadata, name: string, fn: () => Promise<T>): Promise<T> {
  return runWithRequestId(metadataValue(md, REQUEST_ID_HEADER), async () => {
    const started = Date.now();
    try {
      if (!isInternalSecret(metadataValue(md, INTERNAL_SECRET_HEADER))) {
        throw new AppError(403, 'forbidden', 'Chỉ dành cho service nội bộ');
      }
      const result = await fn();
      log.info(`gRPC ${name} OK ${Date.now() - started}ms`);
      return result;
    } catch (exc) {
      if (exc instanceof AppError) log.info(`gRPC ${name} ${exc.status} ${exc.error} ${Date.now() - started}ms`);
      else log.error(`gRPC ${name} failed`, exc);
      throw new RpcException(toGrpcError(exc));
    }
  });
}

export function idempotencyKeyOf(md: Metadata, fromRequest?: string): string | undefined {
  return fromRequest || metadataValue(md, 'idempotency-key');
}
