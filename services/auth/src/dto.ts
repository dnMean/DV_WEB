import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsString, Length } from 'class-validator';

export class LoginIn {
  @ApiProperty({ minLength: 1, maxLength: 50 }) @IsString() @Length(1, 50) username: string;
  @ApiProperty({ minLength: 1, maxLength: 128 }) @IsString() @Length(1, 128) password: string;
}

export class TokenOut {
  @ApiProperty() access_token: string;
  @ApiProperty({ default: 'bearer' }) token_type: string;
  @ApiProperty() role: string;
  @ApiProperty() user_id: number;
}

export class UserOut {
  @ApiProperty() id: number;
  @ApiProperty() username: string;
  @ApiProperty() role: string;
  @ApiPropertyOptional({ nullable: true }) email: string | null;
  @ApiPropertyOptional({ nullable: true }) phone: string | null;
}
