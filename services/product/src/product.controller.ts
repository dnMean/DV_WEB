import { Controller, Get, HttpCode, Param, Post, Query } from '@nestjs/common';
import { ApiExcludeEndpoint, ApiOkResponse, ApiOperation, ApiTags } from '@nestjs/swagger';

import { reset } from './seed';
import { AgentTool, ApiIdParam, IdPipe, InternalOnly, OptionalAuth, resetCount } from './common/nest';
import { ProductOut, SearchQuery, StockOut } from './dto';
import { PrismaService } from './prisma.service';
import { ProductService } from './product.service';

const ROLES = ['customer', 'staff'];

@ApiTags('products')
@Controller()
export class ProductController {
  constructor(private readonly products: ProductService, private readonly db: PrismaService) {}

  @Get('products/search')
  @OptionalAuth()
  @ApiOperation({
    summary: 'Tìm kiếm sản phẩm',
    description: "Dùng khi user hỏi về sản phẩm theo tên hoặc loại (ví dụ 'tai nghe', 'sạc'). "
      + 'Tìm không phân biệt hoa thường và dấu. Trả tối đa `limit` kết quả.',
  })
  @ApiOkResponse({ type: [ProductOut] })
  @AgentTool('search_products', 'low', ROLES)
  search(@Query() query: SearchQuery) {
    return this.products.search(query.q, query.limit);
  }

  @Get('products/:product_id')
  @OptionalAuth()
  @ApiOperation({
    summary: 'Lấy chi tiết sản phẩm',
    description: 'Dùng khi đã biết mã sản phẩm (product_id) và cần giá, mô tả, danh mục.',
  })
  @ApiIdParam('product_id', 'Mã sản phẩm')
  @ApiOkResponse({ type: ProductOut })
  @AgentTool('get_product', 'low', ROLES)
  async get(@Param('product_id', IdPipe) id: number) {
    return ProductService.toOut(await this.products.get(id));
  }

  @Get('inventory/:product_id')
  @OptionalAuth()
  @ApiOperation({
    summary: 'Kiểm tra tồn kho sản phẩm',
    description: 'Dùng khi user hỏi sản phẩm còn hàng không hoặc còn bao nhiêu. Cần product_id.',
  })
  @ApiIdParam('product_id', 'Mã sản phẩm')
  @ApiOkResponse({ type: StockOut })
  @AgentTool('check_stock', 'low', ROLES)
  stock(@Param('product_id', IdPipe) id: number) {
    return this.products.stock(id);
  }

  @Post('internal/reset')
  @HttpCode(200)
  @InternalOnly()
  @ApiExcludeEndpoint()
  async reset(@Query('extra_orders') extraOrders?: string) {
    const extra = resetCount(extraOrders); // the catalog does not depend on generated orders
    await reset(this.db);
    return { status: 'reset', extra_orders: extra };
  }
}
