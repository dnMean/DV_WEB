import { Injectable } from '@nestjs/common';
import { User } from '@prisma/client';
import { compare } from 'bcryptjs';

import { AppError, CurrentUser, createAccessToken, decodeToken, isSystem, log } from './common';
import { TokenOut, UserOut } from './dto';
import { PrismaService } from './prisma.service';

const toOut = (u: User): UserOut => ({ id: u.id, username: u.username, role: u.role, email: u.email, phone: u.phone });

@Injectable()
export class AuthService {
  constructor(private readonly db: PrismaService) {}

  async login(username: string, password: string): Promise<TokenOut> {
    const user = await this.db.user.findUnique({ where: { username } });
    if (!user || !(await compare(password, user.passwordHash))) {
      log.info(`failed login for username=${username}`);
      throw new AppError(401, 'invalid_credentials', 'Sai tên đăng nhập hoặc mật khẩu');
    }
    log.info(`user ${user.id} logged in`);
    return {
      access_token: await createAccessToken(user.id, user.username, user.role),
      token_type: 'bearer', role: user.role, user_id: user.id,
    };
  }

  async getUser(id: number): Promise<UserOut> {
    const user = await this.db.user.findUnique({ where: { id } });
    if (!user) throw new AppError(404, 'user_not_found', 'Không tìm thấy user');
    return toOut(user);
  }

  async me(current: CurrentUser): Promise<UserOut> {
    if (isSystem(current)) return { id: current.id, username: current.username, role: current.role, email: null, phone: null };
    return this.getUser(current.id);
  }

  /** gRPC VerifyToken: the user behind a token (system tokens have no DB row). */
  async verify(token: string): Promise<UserOut> {
    const claims = await decodeToken(token);
    const current = { id: Number(claims.sub), username: String(claims.username ?? ''), role: String(claims.role) };
    return this.me({ ...current, token, onBehalfOf: null });
  }
}
