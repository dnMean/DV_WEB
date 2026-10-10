import 'reflect-metadata';

import { LoggerService, Type } from '@nestjs/common';
import { NestFactory, Reflector } from '@nestjs/core';
import { MicroserviceOptions, Transport } from '@nestjs/microservices';
import type { NestExpressApplication } from '@nestjs/platform-express';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import type { NextFunction, Request, Response } from 'express';

import { envNumber } from '../env';
import { GRPC_PORT, LOADER_OPTIONS, protoPath } from '../grpc';
import { REQUEST_ID_HEADER, getRequestId, log, runWithRequestId, setServiceName } from '../logging';
import { AuthGuard } from './auth';
import { AllExceptionsFilter, validationPipe } from './filters';

const QUIET = new Set(['RoutesResolver', 'RouterExplorer', 'InstanceLoader', 'NestFactory', 'NestApplication',
  'NestMicroservice', 'ServerGrpc']);

/** Routes Nest's own logs through the JSON logger. */
class JsonNestLogger implements LoggerService {
  log(message: unknown, context?: string) {
    if (!QUIET.has(context ?? '')) log.info(`${context ? `[${context}] ` : ''}${String(message)}`);
  }
  error(message: unknown, trace?: string, context?: string) {
    log.error(`${context ? `[${context}] ` : ''}${String(message)}${trace ? `\n${trace}` : ''}`);
  }
  warn(message: unknown, context?: string) {
    log.warn(`${context ? `[${context}] ` : ''}${String(message)}`);
  }
  debug() {}
  verbose() {}
}

function requestIdMiddleware(req: Request, res: Response, next: NextFunction) {
  runWithRequestId(req.header(REQUEST_ID_HEADER), () => {
    const rid = getRequestId();
    const started = process.hrtime.bigint();
    res.setHeader('X-Request-ID', rid);
    res.on('finish', () => {
      if (req.path === '/health') return;
      const ms = Number(process.hrtime.bigint() - started) / 1e6;
      runWithRequestId(rid, () => log.info(`${req.method} ${req.path} ${res.statusCode} ${ms.toFixed(1)}ms`));
    });
    next();
  });
}

export interface ServiceOptions {
  name: string;
  title: string;
  module: Type<unknown>;
  /** proto file (without .proto) whose `opspilot.<name>` package this service implements over gRPC */
  grpc?: string;
  /** e.g. create/seed tables and start the outbox, before any request is served */
  beforeListen?: (app: NestExpressApplication) => Promise<void>;
}

/** HTTP (REST + Swagger at /docs, /openapi.json) on :8000 and gRPC on GRPC_PORT, in one process. */
export async function bootstrap(opts: ServiceOptions): Promise<NestExpressApplication> {
  setServiceName(opts.name);
  const app = await NestFactory.create<NestExpressApplication>(opts.module, { logger: new JsonNestLogger() });
  app.use(requestIdMiddleware);
  app.useGlobalFilters(new AllExceptionsFilter());
  app.useGlobalPipes(validationPipe());
  app.useGlobalGuards(new AuthGuard(app.get(Reflector)));
  app.enableShutdownHooks();

  const config = new DocumentBuilder().setTitle(opts.title).setVersion('0.1.0').addBearerAuth().build();
  const document = SwaggerModule.createDocument(app, config);
  SwaggerModule.setup('docs', app, document);
  const http = app.getHttpAdapter().getInstance() as import('express').Express;
  http.get('/openapi.json', (_req: Request, res: Response) => res.json(document));
  http.get('/health', (_req: Request, res: Response) => res.json({ status: 'ok' }));

  await opts.beforeListen?.(app);
  if (opts.grpc) {
    app.connectMicroservice<MicroserviceOptions>({
      transport: Transport.GRPC,
      options: {
        package: `opspilot.${opts.grpc}`,
        protoPath: protoPath(opts.grpc),
        url: `0.0.0.0:${GRPC_PORT}`,
        loader: LOADER_OPTIONS,
      },
    });
    await app.startAllMicroservices();
  }
  const port = envNumber('PORT', 8000);
  await app.listen(port, '0.0.0.0');
  log.info(`${opts.name} service ready (http :${port}${opts.grpc ? `, grpc :${GRPC_PORT}` : ''})`);
  return app;
}
