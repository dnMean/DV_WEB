import type { Metadata } from '@grpc/grpc-js';
import { Body, Controller, Get, HttpCode, Post } from '@nestjs/common';
import { GrpcMethod } from '@nestjs/microservices';
import { ApiOkResponse, ApiOperation, ApiTags } from '@nestjs/swagger';

import { AuthService } from './auth.service';
import type { CurrentUser } from './common';
import { AuthUser, Roles, handleRpc } from './common/nest';
import { LoginIn, TokenOut, UserOut } from './dto';

@ApiTags('auth')
@Controller('auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Post('login')
  @HttpCode(200)
  @ApiOperation({ summary: 'Đăng nhập, nhận JWT' })
  @ApiOkResponse({ type: TokenOut })
  login(@Body() body: LoginIn) {
    return this.auth.login(body.username, body.password);
  }

  @Get('me')
  @Roles('customer', 'staff', 'system')
  @ApiOperation({ summary: 'Thông tin user hiện tại' })
  @ApiOkResponse({ type: UserOut })
  me(@AuthUser() user: CurrentUser) {
    return this.auth.me(user);
  }
}

const nulls = (u: UserOut) => ({ ...u, email: u.email ?? '', phone: u.phone ?? '' });

/** opspilot.auth.AuthInternal (proto/auth.proto). */
@Controller()
export class AuthGrpcController {
  constructor(private readonly auth: AuthService) {}

  @GrpcMethod('AuthInternal', 'GetUser')
  getUser(req: { user_id: number }, md: Metadata) {
    return handleRpc(md, 'GetUser', async () => nulls(await this.auth.getUser(req.user_id)));
  }

  @GrpcMethod('AuthInternal', 'VerifyToken')
  verifyToken(req: { token: string }, md: Metadata) {
    return handleRpc(md, 'VerifyToken', async () => nulls(await this.auth.verify(req.token)));
  }
}
