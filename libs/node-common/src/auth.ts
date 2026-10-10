/**
 * JWT (HS256, `jose`) issuing and verification.
 *
 * Two secrets:
 * - JWT_SECRET signs normal user tokens (customer/staff) issued by the Auth service.
 * - SYSTEM_TOKEN_SECRET signs `system` tokens that only the Gateway mints when executing an approved
 *   ticket. A `system` role claim signed with JWT_SECRET is rejected.
 */
import { timingSafeEqual } from 'node:crypto';
import { SignJWT, errors, jwtVerify, type JWTPayload } from 'jose';

import { env, envNumber } from './env';
import { AppError } from './errors';

export const SYSTEM_ROLE = 'system';
export const ON_BEHALF_OF_HEADER = 'x-on-behalf-of';
export const INTERNAL_SECRET_HEADER = 'x-internal-secret';

export interface CurrentUser {
  id: number;
  username: string;
  role: string;
  token: string;
  onBehalfOf: number | null; // set only for system tokens
}

export const isStaff = (u: CurrentUser) => u.role === 'staff';
export const isSystem = (u: CurrentUser) => u.role === SYSTEM_ROLE;

const key = (name: string) => new TextEncoder().encode(env(name));

async function sign(claims: Record<string, unknown>, secret: string, ttlMinutes: number): Promise<string> {
  return new SignJWT(claims)
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .setExpirationTime(Math.floor(Date.now() / 1000) + Math.round(ttlMinutes * 60))
    .sign(key(secret));
}

export async function createAccessToken(userId: number, username: string, role: string, ttlMinutes?: number) {
  if (role === SYSTEM_ROLE) throw new Error('system tokens must be created with createSystemToken');
  return sign({ sub: String(userId), username, role }, 'JWT_SECRET', ttlMinutes ?? envNumber('JWT_TTL_MINUTES', 60));
}

export async function createSystemToken(ttlMinutes = 5) {
  return sign({ sub: '0', username: 'system', role: SYSTEM_ROLE }, 'SYSTEM_TOKEN_SECRET', ttlMinutes);
}

const invalid = () => new AppError(401, 'invalid_token', 'Token không hợp lệ');

async function verify(token: string, secret: string): Promise<JWTPayload> {
  const { payload } = await jwtVerify(token, key(secret), { algorithms: ['HS256'], requiredClaims: ['exp', 'sub'] });
  return payload;
}

export async function decodeToken(token: string): Promise<JWTPayload> {
  try {
    const claims = await verify(token, 'JWT_SECRET');
    if (claims.role === SYSTEM_ROLE) throw invalid();
    return claims;
  } catch (exc) {
    if (exc instanceof AppError) throw exc;
    if (exc instanceof errors.JWTExpired) throw new AppError(401, 'token_expired', 'Token đã hết hạn');
    if (!(exc instanceof errors.JWSSignatureVerificationFailed)) throw invalid();
  }
  // not signed with JWT_SECRET: may be a system token
  try {
    const claims = await verify(token, 'SYSTEM_TOKEN_SECRET');
    if (claims.role !== SYSTEM_ROLE) throw invalid();
    return claims;
  } catch (exc) {
    if (exc instanceof AppError) throw exc;
    if (exc instanceof errors.JWTExpired) throw new AppError(401, 'token_expired', 'Token đã hết hạn');
    throw invalid();
  }
}

/** Returns null when no bearer token is sent; throws 401 when a token is sent but invalid. */
export async function userFromHeaders(
  authorization: string | undefined,
  onBehalfOf: string | undefined,
): Promise<CurrentUser | null> {
  const match = /^Bearer\s+(.+)$/i.exec(authorization ?? '');
  if (!match) return null;
  const token = match[1].trim();
  const claims = await decodeToken(token);
  let obo: number | null = null;
  if (claims.role === SYSTEM_ROLE && onBehalfOf !== undefined) {
    if (!/^\d+$/.test(onBehalfOf)) throw new AppError(400, 'bad_request', 'X-On-Behalf-Of phải là user_id dạng số');
    obo = Number(onBehalfOf);
  }
  return {
    id: Number(claims.sub),
    username: String(claims.username ?? ''),
    role: String(claims.role),
    token,
    onBehalfOf: obo,
  };
}

/** Constant-time check of the X-Internal-Secret header / metadata used between services. */
export function isInternalSecret(sent: string | undefined | null): boolean {
  const secret = process.env.INTERNAL_SECRET ?? '';
  if (!secret || !sent) return false;
  const a = Buffer.from(sent);
  const b = Buffer.from(secret);
  return a.length === b.length && timingSafeEqual(a, b);
}
