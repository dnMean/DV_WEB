import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsIn, IsInt, IsOptional, IsString, Length, Matches, Max, MaxLength, Min } from 'class-validator';

export const SHIPMENT_STATUSES = ['WAITING_PICKUP', 'IN_TRANSIT', 'DELIVERED', 'CANCELLED'] as const;
export const PHONE = /^(\+84|0)\d{9}$/;

export class ShipmentEventOut {
  @ApiProperty() status: string;
  @ApiProperty() location: string;
  @ApiProperty() description: string;
  @ApiProperty() occurred_at: string;
}

export class ShipmentOut {
  @ApiProperty() order_id: number;
  @ApiProperty() user_id: number;
  @ApiProperty({ enum: SHIPMENT_STATUSES }) status: string;
  @ApiProperty() carrier: string;
  @ApiProperty() tracking_code: string;
  @ApiProperty() recipient_name: string;
  @ApiProperty() recipient_phone: string;
  @ApiProperty() address: string;
  @ApiProperty() updated_at: string;
  @ApiProperty({ type: [ShipmentEventOut] }) events: ShipmentEventOut[];
}

export class ListQuery {
  @ApiPropertyOptional({ enum: SHIPMENT_STATUSES })
  @IsOptional() @IsIn(SHIPMENT_STATUSES)
  status?: string;

  @ApiPropertyOptional({ type: 'integer', default: 500, minimum: 1, maximum: 1000 })
  @IsOptional() @IsInt() @Min(1) @Max(1000)
  limit: number = 500;
}

export class AddressUpdateIn {
  @ApiProperty({ minLength: 5, maxLength: 300, description: 'Địa chỉ giao hàng mới, đầy đủ' })
  @IsString() @Length(5, 300)
  address: string;

  @ApiPropertyOptional({ minLength: 1, maxLength: 100, description: 'Tên người nhận mới (tuỳ chọn)' })
  @IsOptional() @IsString() @Length(1, 100)
  recipient_name?: string;

  @ApiPropertyOptional({ pattern: PHONE.source, description: 'Số điện thoại người nhận mới (tuỳ chọn)' })
  @IsOptional() @IsString() @Matches(PHONE)
  recipient_phone?: string;
}

export class AdvanceIn {
  @ApiProperty({
    enum: ['IN_TRANSIT', 'DELIVERED'],
    description: 'IN_TRANSIT: đã lấy hàng / đang giao / cập nhật vị trí; DELIVERED: đã giao thành công',
  })
  @IsIn(['IN_TRANSIT', 'DELIVERED'])
  status: 'IN_TRANSIT' | 'DELIVERED';

  @ApiPropertyOptional({ default: '', maxLength: 100, description: 'Vị trí hiện tại (tuỳ chọn), vd Kho Hà Nội' })
  @IsOptional() @IsString() @MaxLength(100)
  location: string = '';

  @ApiPropertyOptional({ default: '', maxLength: 300, description: 'Ghi chú (tuỳ chọn)' })
  @IsOptional() @IsString() @MaxLength(300)
  description: string = '';
}
