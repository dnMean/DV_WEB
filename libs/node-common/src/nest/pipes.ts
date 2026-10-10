import { ArgumentMetadata, Injectable, PipeTransform } from '@nestjs/common';
import { ApiParam } from '@nestjs/swagger';

import { AppError } from '../errors';

/** Path parameter that must be an integer >= 1 (422 validation_error otherwise). */
@Injectable()
export class IdPipe implements PipeTransform<string, number> {
  transform(value: string, meta: ArgumentMetadata): number {
    if (!/^\d+$/.test(String(value)) || Number(value) < 1) {
      throw new AppError(422, 'validation_error', `${meta.data}: phải là số nguyên ≥ 1`);
    }
    return Number(value);
  }
}

/** OpenAPI description of an integer id path parameter (becomes the tool argument's schema). */
export const ApiIdParam = (name: string, description: string) =>
  ApiParam({ name, description, required: true, schema: { type: 'integer', minimum: 1 } });
