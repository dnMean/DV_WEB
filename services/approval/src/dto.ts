import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsIn, IsInt, IsOptional, IsString, Max, MaxLength, Min } from 'class-validator';

export const TICKET_STATUSES = ['PENDING', 'APPROVED', 'REJECTED', 'EXECUTED', 'FAILED'] as const;

export class TicketOut {
  @ApiProperty() id: string;
  @ApiProperty() conversation_id: string;
  @ApiProperty() user_id: number;
  @ApiProperty() tool: string;
  @ApiProperty({ type: 'object', additionalProperties: true }) arguments: Record<string, unknown>;
  @ApiProperty({ enum: TICKET_STATUSES }) status: string;
  @ApiProperty({ nullable: true, type: Number }) reviewer_id: number | null;
  @ApiProperty({ nullable: true, type: String }) review_note: string | null;
  @ApiProperty({ nullable: true, type: 'object', additionalProperties: true }) result: Record<string, unknown> | null;
  @ApiProperty() created_at: string;
  @ApiProperty() updated_at: string;
}

export class TicketListQuery {
  @ApiPropertyOptional({ enum: TICKET_STATUSES, description: 'Lọc theo trạng thái, vd PENDING' })
  @IsOptional() @IsIn(TICKET_STATUSES)
  status?: string;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, maximum: 200, default: 20, description: 'Số ticket tối đa' })
  @IsOptional() @IsInt() @Min(1) @Max(200)
  limit: number = 20;
}

export class ReviewIn {
  @ApiPropertyOptional({ default: '', maxLength: 1000, description: 'Ghi chú / lý do của staff' })
  @IsOptional() @IsString() @MaxLength(1000)
  note: string = '';
}

export class RefundRequestOut {
  @ApiProperty() ticket_id: string;
  @ApiProperty({ nullable: true, type: Number }) order_id: number | null;
  @ApiProperty() user_id: number;
  @ApiProperty({ nullable: true, type: Number }) amount: number | null;
  @ApiProperty() reason: string;
  @ApiProperty({ enum: TICKET_STATUSES }) status: string;
  @ApiProperty({ nullable: true, type: String }) review_note: string | null;
  @ApiProperty({ nullable: true, type: String }) failure: string | null;
  @ApiProperty() created_at: string;
  @ApiProperty() updated_at: string;
}

export class RefundRequestQuery {
  @ApiPropertyOptional({ enum: TICKET_STATUSES, description: 'Lọc theo trạng thái yêu cầu' })
  @IsOptional() @IsIn(TICKET_STATUSES)
  status?: string;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, description: 'Lọc theo mã đơn' })
  @IsOptional() @IsInt() @Min(1)
  order_id?: number;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, description: 'Chỉ staff: lọc theo khách' })
  @IsOptional() @IsInt() @Min(1)
  user_id?: number;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, maximum: 100, default: 20, description: 'Số yêu cầu tối đa' })
  @IsOptional() @IsInt() @Min(1) @Max(100)
  limit: number = 20;
}
