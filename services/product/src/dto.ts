import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsInt, IsOptional, IsString, Length, Max, Min } from 'class-validator';

export class SearchQuery {
  @ApiProperty({ description: 'Từ khoá tìm kiếm', minLength: 1, maxLength: 100 })
  @IsString() @Length(1, 100)
  q: string;

  @ApiPropertyOptional({ type: 'integer', minimum: 1, maximum: 20, default: 5, description: 'Số kết quả tối đa' })
  @IsOptional() @IsInt() @Min(1) @Max(20)
  limit: number = 5;
}

export class ProductOut {
  @ApiProperty() id: number;
  @ApiProperty() sku: string;
  @ApiProperty() name: string;
  @ApiProperty() category: string;
  @ApiProperty() description: string;
  @ApiProperty({ description: 'Giá (VND)' }) price: number;
  @ApiProperty() in_stock: boolean;
}

export class StockOut {
  @ApiProperty() product_id: number;
  @ApiProperty() name: string;
  @ApiProperty() stock: number;
  @ApiProperty() in_stock: boolean;
}
