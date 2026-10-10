import { ApiProperty } from '@nestjs/swagger';
import { IsInt, IsString, Length, Min } from 'class-validator';

export class RefundOut {
  @ApiProperty() id: number;
  @ApiProperty() order_id: number;
  @ApiProperty() amount: number;
  @ApiProperty() reason: string;
  @ApiProperty() status: string;
  @ApiProperty() created_at: string;
}

export class PaymentOut {
  @ApiProperty() id: number;
  @ApiProperty() order_id: number;
  @ApiProperty() user_id: number;
  @ApiProperty() amount: number;
  @ApiProperty() method: string;
  @ApiProperty({ enum: ['SUCCESS', 'PARTIALLY_REFUNDED', 'REFUNDED'] }) status: string;
  @ApiProperty() refunded_amount: number;
  @ApiProperty() refundable_amount: number;
  @ApiProperty({ type: [RefundOut] }) refunds: RefundOut[];
  @ApiProperty() created_at: string;
}

export class OrderIdQuery {
  @ApiProperty({ type: 'integer', minimum: 1, description: 'Mã đơn hàng' })
  @IsInt() @Min(1)
  order_id: number;
}

export class RefundIn {
  @ApiProperty({ type: 'integer', minimum: 1, description: 'Mã đơn hàng cần hoàn tiền' })
  @IsInt() @Min(1)
  order_id: number;

  @ApiProperty({ type: 'integer', minimum: 1, description: 'Số tiền hoàn (VND), không vượt quá số tiền còn có thể hoàn' })
  @IsInt() @Min(1)
  amount: number;

  @ApiProperty({ minLength: 1, maxLength: 500, description: 'Lý do hoàn tiền do khách nêu' })
  @IsString() @Length(1, 500)
  reason: string;
}

export class RefundResultOut {
  @ApiProperty({ type: RefundOut }) refund: RefundOut;
  @ApiProperty({ description: 'true nếu Idempotency-Key đã được dùng và đây là kết quả cũ' }) replayed: boolean;
  @ApiProperty() refundable_amount: number;
}

export class RefundCheckOut {
  @ApiProperty() eligible: boolean;
  @ApiProperty() order_status: string;
  @ApiProperty() refundable_amount: number;
  @ApiProperty() full_refund_required: boolean;
}

export class EligibilityOut {
  @ApiProperty() order_id: number;
  @ApiProperty() eligible: boolean;
  @ApiProperty({ description: 'ok | order_not_paid | order_in_transit | order_not_refundable' }) reason: string;
  @ApiProperty() message: string;
  @ApiProperty() max_refundable: number;
  @ApiProperty() full_refund_required: boolean;
}
