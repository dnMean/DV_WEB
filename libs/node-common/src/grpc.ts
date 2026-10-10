/**
 * gRPC between services (contracts in /proto).
 *
 * Business errors cross the wire as a gRPC status whose `details` is the JSON error body plus the HTTP status
 * it stands for, so the caller can react exactly as it would to an HTTP answer (404 vs 409 vs 503).
 */
import path from 'node:path';

import * as grpc from '@grpc/grpc-js';
import * as protoLoader from '@grpc/proto-loader';

import { INTERNAL_SECRET_HEADER } from './auth';
import { env, envNumber } from './env';
import { AppError } from './errors';
import { REQUEST_ID_HEADER, getRequestId } from './logging';

export const GRPC_PORT = envNumber('GRPC_PORT', 50051);
export const LOADER_OPTIONS: protoLoader.Options = {
  keepCase: true,
  longs: Number,
  enums: String,
  defaults: true,
  oneofs: true,
};

export function protoPath(name: string): string {
  return path.join(env('PROTO_DIR', path.resolve(process.cwd(), '../../proto')), `${name}.proto`);
}

const HTTP_TO_GRPC: Record<number, grpc.status> = {
  400: grpc.status.INVALID_ARGUMENT,
  401: grpc.status.UNAUTHENTICATED,
  403: grpc.status.PERMISSION_DENIED,
  404: grpc.status.NOT_FOUND,
  409: grpc.status.FAILED_PRECONDITION,
  422: grpc.status.INVALID_ARGUMENT,
  429: grpc.status.RESOURCE_EXHAUSTED,
  503: grpc.status.UNAVAILABLE,
  504: grpc.status.DEADLINE_EXCEEDED,
};

/** Server side: any thrown value -> {code, message} understood by grpc-js. */
export function toGrpcError(exc: unknown): { code: grpc.status; message: string } {
  const err = exc instanceof AppError ? exc : new AppError(500, 'internal_error', 'Lỗi hệ thống');
  return {
    code: HTTP_TO_GRPC[err.status] ?? grpc.status.INTERNAL,
    message: JSON.stringify({ http_status: err.status, ...err.body() }),
  };
}

/** Client side: a failed call. `status` is the HTTP-equivalent status (503 when the service is unreachable). */
export class RpcCallError extends Error {
  constructor(
    readonly code: grpc.status,
    readonly status: number,
    readonly error: string,
    message: string,
    readonly extra: Record<string, unknown> = {},
  ) {
    super(message);
  }

  /** Transient: worth retrying later (network, timeout, overload, 5xx). */
  get retryable(): boolean {
    return this.status >= 500 || this.status === 408 || this.status === 429;
  }
}

function decode(err: grpc.ServiceError): RpcCallError {
  try {
    const { http_status, error, message, ...extra } = JSON.parse(err.details);
    if (typeof http_status === 'number' && typeof error === 'string') {
      return new RpcCallError(err.code, http_status, error, String(message ?? ''), extra);
    }
  } catch {
    // not one of our errors (connection refused, deadline, ...)
  }
  const status = err.code === grpc.status.DEADLINE_EXCEEDED ? 504 : 503;
  return new RpcCallError(err.code, status, 'dependency_unavailable', `${grpc.status[err.code]}: ${err.details}`);
}

type Method = (req: unknown, md: grpc.Metadata, opts: grpc.CallOptions, cb: grpc.requestCallback<unknown>) => void;

/** Promise-based client for one service of a proto package, e.g. grpcClient('product', 'ProductInternal', addr). */
export class GrpcClient {
  private readonly client: grpc.Client & Record<string, Method>;

  constructor(
    proto: string,
    service: string,
    readonly address: string,
    private readonly timeoutMs = envNumber('DEPENDENCY_TIMEOUT_SECONDS', 5) * 1000,
  ) {
    const definition = protoLoader.loadSync(protoPath(proto), LOADER_OPTIONS);
    const pkg = grpc.loadPackageDefinition(definition) as unknown as Record<string, Record<string, Record<string, grpc.ServiceClientConstructor>>>;
    const Ctor = pkg.opspilot[proto][service];
    this.client = new Ctor(address, grpc.credentials.createInsecure()) as never;
  }

  call<T>(method: string, request: object, opts: { idempotencyKey?: string; timeoutMs?: number } = {}): Promise<T> {
    const md = new grpc.Metadata();
    md.set(INTERNAL_SECRET_HEADER, env('INTERNAL_SECRET', ''));
    const rid = getRequestId();
    if (rid !== '-') md.set(REQUEST_ID_HEADER, rid);
    if (opts.idempotencyKey) md.set('idempotency-key', opts.idempotencyKey);
    const fn = this.client[method];
    if (typeof fn !== 'function') return Promise.reject(new Error(`unknown rpc ${method}`));
    return new Promise((resolve, reject) => {
      fn.call(this.client, request, md, { deadline: Date.now() + (opts.timeoutMs ?? this.timeoutMs) },
        (err: grpc.ServiceError | null, reply: unknown) => (err ? reject(decode(err)) : resolve(reply as T)));
    });
  }

  close(): void {
    this.client.close();
  }
}

export function metadataValue(md: grpc.Metadata | undefined, key: string): string | undefined {
  const value = md?.get(key)?.[0];
  return value === undefined ? undefined : String(value);
}
