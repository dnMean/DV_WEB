import {
  CanActivate, ExecutionContext, Injectable, SetMetadata, applyDecorators, createParamDecorator,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { ApiBearerAuth } from '@nestjs/swagger';
import type { Request } from 'express';

import { CurrentUser, INTERNAL_SECRET_HEADER, ON_BEHALF_OF_HEADER, isInternalSecret, userFromHeaders } from '../auth';
import { AppError } from '../errors';

const ROLES_KEY = 'opspilot:roles';
const OPTIONAL_KEY = 'opspilot:optional-auth';
const INTERNAL_KEY = 'opspilot:internal';

type AuthedRequest = Request & { user?: CurrentUser | null };

/** Require a valid token whose role is one of `roles` (401 without token, 403 for another role). */
export const Roles = (...roles: string[]) => applyDecorators(SetMetadata(ROLES_KEY, roles), ApiBearerAuth());

/** Token is optional, but must be valid when sent. */
export const OptionalAuth = () => SetMetadata(OPTIONAL_KEY, true);

/** Service-to-service HTTP endpoint (X-Internal-Secret). */
export const InternalOnly = () => SetMetadata(INTERNAL_KEY, true);

/** The authenticated user (null on endpoints with optional auth and no token). */
export const AuthUser = createParamDecorator(
  (_: unknown, ctx: ExecutionContext) => ctx.switchToHttp().getRequest<AuthedRequest>().user ?? null,
);

export function isInternalRequest(req: Request): boolean {
  return isInternalSecret(req.header(INTERNAL_SECRET_HEADER));
}

@Injectable()
export class AuthGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  async canActivate(ctx: ExecutionContext): Promise<boolean> {
    if (ctx.getType() !== 'http') return true; // gRPC handlers check the internal secret themselves
    const targets = [ctx.getHandler(), ctx.getClass()];
    const req = ctx.switchToHttp().getRequest<AuthedRequest>();

    if (this.reflector.getAllAndOverride<boolean>(INTERNAL_KEY, targets)) {
      if (!isInternalRequest(req)) throw new AppError(403, 'forbidden', 'Chỉ dành cho service nội bộ');
      return true;
    }
    const roles = this.reflector.getAllAndOverride<string[] | undefined>(ROLES_KEY, targets);
    const optional = this.reflector.getAllAndOverride<boolean>(OPTIONAL_KEY, targets);
    if (!roles && !optional) return true;

    req.user = await userFromHeaders(req.header('authorization'), req.header(ON_BEHALF_OF_HEADER));
    if (roles) {
      if (!req.user) throw new AppError(401, 'unauthorized', 'Thiếu token xác thực');
      if (!roles.includes(req.user.role)) {
        throw new AppError(403, 'forbidden', `Role '${req.user.role}' không có quyền thực hiện thao tác này`);
      }
    }
    return true;
  }
}
