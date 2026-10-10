import { ArgumentsHost, Catch, ExceptionFilter, HttpException, ValidationError, ValidationPipe } from '@nestjs/common';
import type { Response } from 'express';

import { AppError, DEFAULT_CODES, errorBody } from '../errors';
import { log } from '../logging';

/** Every HTTP error leaves as {"error": "<code>", "message": "<text>"}. */
@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  catch(exc: unknown, host: ArgumentsHost): void {
    if (host.getType() !== 'http') throw exc;
    const res = host.switchToHttp().getResponse<Response>();
    if (exc instanceof AppError) {
      res.status(exc.status).json(exc.body());
      return;
    }
    if (exc instanceof HttpException) {
      const status = exc.getStatus();
      const detail = exc.getResponse();
      const message = typeof detail === 'string' ? detail
        : Array.isArray((detail as { message?: unknown }).message) ? (detail as { message: string[] }).message.join('; ')
          : String((detail as { message?: unknown }).message ?? exc.message);
      res.status(status).json(errorBody(DEFAULT_CODES[status] ?? 'error', message));
      return;
    }
    if ((exc as { type?: string })?.type === 'entity.parse.failed') { // malformed JSON body
      res.status(422).json(errorBody('validation_error', 'Body không phải JSON hợp lệ'));
      return;
    }
    log.error(`unhandled error: ${String(exc)}`, exc);
    res.status(500).json(errorBody('internal_error', 'Lỗi hệ thống'));
  }
}

function flatten(errors: ValidationError[], prefix = ''): string[] {
  return errors.flatMap((e) => {
    const where = prefix ? `${prefix}.${e.property}` : e.property;
    const own = Object.values(e.constraints ?? {}).map((m) => `${where}: ${m}`);
    return [...own, ...flatten(e.children ?? [], where)];
  });
}

/** DTO validation (class-validator); errors -> 422 validation_error. */
export function validationPipe(): ValidationPipe {
  return new ValidationPipe({
    transform: true,
    whitelist: true,
    transformOptions: { enableImplicitConversion: true },
    exceptionFactory: (errors) => {
      const parts = flatten(errors).slice(0, 3);
      return new AppError(422, 'validation_error', parts.join('; ') || 'Dữ liệu không hợp lệ');
    },
  });
}
