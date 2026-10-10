import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Transform, Type } from 'class-transformer';
import {
  ArrayMaxSize, ArrayMinSize, IsArray, IsBoolean, IsIn, IsInt, IsOptional, IsString, Length, Matches, Max, Min,
  ValidateNested,
} from 'class-validator';

export const ORDER_STATUSES = ['PENDING', 'PAID', 'SHIPPING', 'DELIVERED', 'CANCELLED', 'REFUNDED'] as const;
const PHONE = /^(\+84|0)\d{9}$/;

export class OrderItemOut {
  @ApiProperty() product_id: number;
  @ApiProperty() name: string;
  @ApiProperty() qty: number;
  @ApiProperty() price: number;
}

export class OrderOut {
  @ApiProperty() id: number;
  @ApiProperty() user_id: number;
  @ApiProperty({ enum: ORDER_STATUSES }) status: string;
  @ApiProperty() total: number;
  @ApiProperty() refunded_amount: number;
  @ApiProperty({ type: [OrderItemOut] }) items: OrderItemOut[];
  @ApiProperty({ nullable: true, type: String }) note: string | null;
  @ApiProperty() created_at: string;
}

/** Compact row for list endpoints (keeps tool results small); use get_order for details and note. */
export class OrderSummaryOut {
  @ApiProperty() id: number;
  @ApiProperty() user_id: number;
  @ApiProperty({ enum: ORDER_STATUSES }) status: string;
  @ApiProperty() total: number;
  @ApiProperty() refunded_amount: number;
  @ApiProperty({ description: 'vd "Sạc nhanh Anker 20W USB-C x2"' }) items: string;
  @ApiProperty() created_at: string;
}

export class OrderPage {
  @ApiProperty() total: number;
  @ApiProperty() offset: number;
  @ApiProperty() limit: number;
  @ApiProperty() has_more: boolean;
  @ApiProperty({ type: [OrderSummaryOut] }) orders: OrderSummaryOut[];
}

const toBool = ({ obj, key }: { obj: Record<string, unknown>; key: string }) => {
  const raw = obj[key];
  if (raw === 'true' || raw === true) return true;
  if (raw === 'false' || raw === false) return false;
  return raw;
};

export class ListOrdersQuery {
  @ApiPropertyOptional({ enum: ORDER_STATUSES, description: 'Lọc theo trạng thái đơn' })
  @IsOptional() @IsIn(ORDER_STATUSES)
  status?: string;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, description: 'Chỉ staff: lọc theo user_id của khách' })
  @IsOptional() @IsInt() @Min(1)
  user_id?: number;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, maximum: 50, default: 20, description: 'Số đơn tối đa trả về trong một trang' })
  @IsOptional() @IsInt() @Min(1) @Max(50)
  limit: number = 20;

  @ApiPropertyOptional({ type: 'integer', minimum: 0, default: 0, description: 'Bỏ qua bao nhiêu đơn (phân trang)' })
  @IsOptional() @IsInt() @Min(0)
  offset: number = 0;
}

export class SearchOrdersQuery {
  @ApiPropertyOptional({ type: 'integer', minimum: 1, description: 'Lọc theo user_id của khách' })
  @IsOptional() @IsInt() @Min(1)
  user_id?: number;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, description: 'Lọc theo mã đơn' })
  @IsOptional() @IsInt() @Min(1)
  order_id?: number;

  @ApiPropertyOptional({ enum: ORDER_STATUSES, description: 'Lọc theo trạng thái đơn' })
  @IsOptional() @IsIn(ORDER_STATUSES)
  status?: string;

  @ApiPropertyOptional({ type: 'boolean', description: 'true: chỉ đơn đã có hoàn tiền; false: chỉ đơn chưa hoàn' })
  @IsOptional() @Transform(toBool) @IsBoolean()
  refunded?: boolean;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, maximum: 200, default: 20, description: 'Số đơn tối đa trong một trang' })
  @IsOptional() @IsInt() @Min(1) @Max(200)
  limit: number = 20;

  @ApiPropertyOptional({ type: 'integer', minimum: 0, default: 0, description: 'Bỏ qua bao nhiêu đơn (phân trang)' })
  @IsOptional() @IsInt() @Min(0)
  offset: number = 0;
}

// --- ordering by chat (docs/USECASES.md section 3b) ------------------------------------------

export class QuoteItemIn {
  @ApiProperty({ type: 'integer', minimum: 1, description: 'Mã sản phẩm (lấy từ search_products)' })
  @IsInt() @Min(1)
  product_id: number;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, maximum: 10, default: 1, description: 'Số lượng' })
  @IsOptional() @IsInt() @Min(1) @Max(10)
  qty: number = 1;
}

export class QuoteIn {
  @ApiProperty({ type: [QuoteItemIn], minItems: 1, maxItems: 10, description: 'Sản phẩm khách muốn mua' })
  @IsArray() @ArrayMinSize(1) @ArrayMaxSize(10) @ValidateNested({ each: true }) @Type(() => QuoteItemIn)
  items: QuoteItemIn[];

  @ApiProperty({ minLength: 1, maxLength: 100, description: 'Tên người nhận do khách cung cấp' })
  @IsString() @Length(1, 100)
  recipient_name: string;

  @ApiProperty({ pattern: PHONE.source, description: 'Số điện thoại người nhận do khách cung cấp' })
  @IsString() @Matches(PHONE)
  recipient_phone: string;

  @ApiProperty({ minLength: 10, maxLength: 300, description: 'Địa chỉ giao hàng đầy đủ do khách cung cấp' })
  @IsString() @Length(10, 300)
  address: string;
}

export class QuoteLineOut {
  @ApiProperty() product_id: number;
  @ApiProperty() name: string;
  @ApiProperty() qty: number;
  @ApiProperty() price: number;
  @ApiProperty() subtotal: number;
}

export class QuoteOut {
  @ApiProperty({ description: 'Mã báo giá; khách phải tự gõ mã này để xác nhận đặt hàng' }) quote_id: string;
  @ApiProperty({ type: [QuoteLineOut] }) items: QuoteLineOut[];
  @ApiProperty() total: number;
  @ApiProperty() recipient_name: string;
  @ApiProperty() recipient_phone: string;
  @ApiProperty() address: string;
  @ApiProperty() expires_in_minutes: number;
  @ApiProperty({ nullable: true, type: Number, description: 'Đơn đã đặt từ báo giá này (nếu có)' }) order_id: number | null;
  @ApiProperty() next_step: string;
}

export class PlaceIn {
  @ApiProperty({ pattern: '^[A-Za-z0-9]{6}$', description: 'Mã báo giá khách đã gõ để xác nhận' })
  @IsString() @Matches(/^[A-Za-z0-9]{6}$/)
  quote_id: string;
}

export class DeliveryOut {
  @ApiProperty() recipient_name: string;
  @ApiProperty() recipient_phone: string;
  @ApiProperty() address: string;
}

export class PlacedOut {
  @ApiProperty({ type: OrderOut }) order: OrderOut;
  @ApiProperty({ type: DeliveryOut }) delivery: DeliveryOut;
  @ApiProperty() next_step: string;
}

export const PAY_METHODS = ['CARD', 'BANK_TRANSFER', 'E_WALLET'] as const;

export class PayIn {
  // prepaid only: COD collects money on delivery, so the order could not be PAID now
  @ApiProperty({
    enum: PAY_METHODS,
    description: 'Phương thức khách chọn: CARD (thẻ), BANK_TRANSFER (chuyển khoản), E_WALLET (ví điện tử). '
      + 'Không hỗ trợ COD (trả khi nhận hàng)',
  })
  @IsIn(PAY_METHODS)
  method: (typeof PAY_METHODS)[number];

  @ApiPropertyOptional({ minLength: 1, maxLength: 100, description: 'Chỉ khi đơn chưa có thông tin giao hàng: tên người nhận' })
  @IsOptional() @IsString() @Length(1, 100)
  recipient_name?: string;

  @ApiPropertyOptional({ pattern: PHONE.source, description: 'Chỉ khi đơn chưa có thông tin giao hàng: số điện thoại' })
  @IsOptional() @IsString() @Matches(PHONE)
  recipient_phone?: string;

  @ApiPropertyOptional({ minLength: 10, maxLength: 300, description: 'Chỉ khi đơn chưa có thông tin giao hàng: địa chỉ' })
  @IsOptional() @IsString() @Length(10, 300)
  address?: string;
}

export class PaidOut {
  @ApiProperty({ type: OrderOut }) order: OrderOut;
  @ApiProperty({ description: '{amount, method, status}' }) payment: { amount: number; method: string; status: string };
  @ApiProperty({ type: DeliveryOut }) delivery: DeliveryOut;
  @ApiProperty() next_step: string;
}
