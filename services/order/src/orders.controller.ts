import type { Metadata } from '@grpc/grpc-js';
import { Body, Controller, Get, HttpCode, Param, Post, Query } from '@nestjs/common';
import { GrpcMethod } from '@nestjs/microservices';
import { ApiCreatedResponse, ApiExcludeEndpoint, ApiOkResponse, ApiOperation, ApiTags } from '@nestjs/swagger';
import { Prisma } from '@prisma/client';

import { CheckoutService } from './checkout.service';
import { AppError, CurrentUser, isStaff } from './common';
import { AgentTool, ApiIdParam, AuthUser, IdPipe, InternalOnly, Roles, handleRpc, resetCount } from './common/nest';
import {
  ListOrdersQuery, OrderOut, OrderPage, PaidOut, PayIn, PlaceIn, PlacedOut, QuoteIn, QuoteOut, SearchOrdersQuery,
} from './dto';
import { FullOrder, OrdersService, toOrderOut } from './orders.service';
import { PrismaService } from './prisma.service';
import { reset } from './seed';

const PAGE_HINT = "Trả {total: tổng số đơn khớp bộ lọc, has_more, orders: một trang đơn tóm tắt, mới nhất trước}. "
  + "Khi được hỏi 'bao nhiêu đơn' thì trả lời theo total, không đếm số dòng trong trang. "
  + 'Dùng offset để xem trang tiếp; cần chi tiết/ghi chú thì dùng get_order.';

@ApiTags('orders')
@Controller()
export class OrdersController {
  constructor(
    private readonly orders: OrdersService,
    private readonly checkout: CheckoutService,
    private readonly db: PrismaService,
  ) {}

  @Get('orders')
  @Roles('customer', 'staff')
  @ApiOperation({
    summary: 'Liệt kê đơn hàng của tôi',
    description: 'Dùng khi user muốn xem hoặc đếm đơn hàng của mình, hoặc chưa nêu mã đơn cụ thể. '
      + 'Customer chỉ thấy đơn của chính mình; dùng status để lọc. ' + PAGE_HINT,
  })
  @ApiOkResponse({ type: OrderPage })
  @AgentTool('list_my_orders', 'low', ['customer'])
  list(@Query() q: ListOrdersQuery, @AuthUser() user: CurrentUser) {
    const where: Prisma.OrderWhereInput = {};
    if (isStaff(user)) {
      if (q.user_id !== undefined) where.userId = q.user_id;
    } else {
      if (q.user_id !== undefined && q.user_id !== user.id) {
        throw new AppError(403, 'forbidden', 'Bạn chỉ được xem đơn hàng của chính mình');
      }
      where.userId = user.id;
    }
    if (q.status) where.status = q.status;
    return this.orders.page(where, q.limit, q.offset);
  }

  @Get('orders/search')
  @Roles('staff')
  @ApiOperation({
    summary: 'Tìm đơn hàng (staff)',
    description: 'Chỉ dành cho staff. Tìm trong toàn bộ đơn hàng, lọc theo khách (user_id), mã đơn (order_id), trạng thái '
      + '(PENDING chờ thanh toán, PAID đã thanh toán chưa giao, SHIPPING đang giao, DELIVERED đã giao, CANCELLED đã huỷ, '
      + 'REFUNDED đã hoàn toàn bộ) hoặc refunded=true để lấy các đơn đã có hoàn tiền (kể cả hoàn một phần). ' + PAGE_HINT,
  })
  @ApiOkResponse({ type: OrderPage })
  @AgentTool('search_orders', 'low', ['staff'])
  search(@Query() q: SearchOrdersQuery) {
    const where: Prisma.OrderWhereInput = {};
    if (q.user_id !== undefined) where.userId = q.user_id;
    if (q.order_id !== undefined) where.id = q.order_id;
    if (q.status) where.status = q.status;
    if (q.refunded !== undefined) where.refundedAmount = q.refunded ? { gt: 0 } : 0;
    return this.orders.page(where, q.limit, q.offset);
  }

  @Get('orders/:order_id')
  @Roles('customer', 'staff')
  @ApiOperation({
    summary: 'Lấy thông tin một đơn hàng',
    description: 'Dùng khi user hỏi trạng thái, sản phẩm, tổng tiền của một đơn cụ thể. '
      + 'Cần mã đơn (order_id). Customer chỉ xem được đơn của mình.',
  })
  @ApiIdParam('order_id', 'Mã đơn hàng, ví dụ 1002')
  @ApiOkResponse({ type: OrderOut })
  @AgentTool('get_order', 'low', ['customer', 'staff'])
  async get(@Param('order_id', IdPipe) orderId: number, @AuthUser() user: CurrentUser) {
    return toOrderOut(await this.orders.get(orderId, user));
  }

  @Post('orders/:order_id/cancel')
  @HttpCode(200)
  @Roles('customer', 'staff')
  @ApiOperation({
    summary: 'Huỷ đơn hàng chưa thanh toán',
    description: 'Dùng khi user yêu cầu rõ ràng huỷ một đơn cụ thể: gọi ngay, không tự đoán trạng thái đơn. Hệ thống tự '
      + 'kiểm tra điều kiện (chỉ đơn chưa thanh toán mới huỷ được) và trả lỗi kèm gợi ý nếu không huỷ được '
      + '(vd đơn đã thanh toán thì khách cần yêu cầu hoàn toàn bộ tiền).',
  })
  @ApiIdParam('order_id', 'Mã đơn hàng cần huỷ')
  @ApiOkResponse({ type: OrderOut })
  @AgentTool('cancel_order', 'medium', ['customer', 'staff'])
  async cancel(@Param('order_id', IdPipe) orderId: number, @AuthUser() user: CurrentUser) {
    return toOrderOut(await this.orders.cancel(orderId, user));
  }

  // --- ordering by chat ---------------------------------------------------------------------

  @Post('orders/quotes')
  @Roles('customer')
  @ApiOperation({
    summary: 'Báo giá trước khi đặt hàng',
    description: 'Dùng khi khách muốn mua/đặt sản phẩm và đã nêu sản phẩm (product_id từ search_products), số lượng, '
      + 'tên người nhận, số điện thoại và địa chỉ giao hàng. Trả mã báo giá (quote_id), giá từng món, tổng tiền. '
      + "CHƯA tạo đơn: trình bày báo giá và hướng dẫn khách gõ 'xác nhận <quote_id>' để đặt hàng.",
  })
  @ApiCreatedResponse({ type: QuoteOut })
  @AgentTool('quote_order', 'low', ['customer'])
  quote(@Body() body: QuoteIn, @AuthUser() user: CurrentUser) {
    return this.checkout.quote(body, user);
  }

  @Post('orders')
  @Roles('customer')
  @ApiOperation({
    summary: 'Đặt hàng theo báo giá',
    description: 'Dùng khi khách xác nhận đặt hàng và tự gõ mã báo giá (quote_id) trong tin nhắn hiện tại. Tạo đơn chờ '
      + 'thanh toán và giữ hàng trong kho. Nếu khách chưa gõ mã báo giá thì không gọi, hãy nhắc khách gõ.',
  })
  @ApiCreatedResponse({ type: PlacedOut })
  @AgentTool('place_order', 'medium', ['customer'], { confirmArgs: ['quote_id'] })
  place(@Body() body: PlaceIn, @AuthUser() user: CurrentUser) {
    return this.checkout.place(body.quote_id, user);
  }

  @Post('orders/:order_id/pay')
  @HttpCode(200)
  @Roles('customer')
  @ApiOperation({
    summary: 'Thanh toán đơn hàng (giả lập)',
    description: 'Dùng khi khách yêu cầu thanh toán một đơn cụ thể, tự gõ mã đơn và chọn phương thức. Gọi ngay, không tự '
      + 'đoán trạng thái đơn: hệ thống tự kiểm tra và trả lỗi nếu không thanh toán được. Sau khi thanh toán, đơn '
      + 'chuyển sang đã thanh toán và vận đơn được tạo.',
  })
  @ApiIdParam('order_id', 'Mã đơn hàng cần thanh toán')
  @ApiOkResponse({ type: PaidOut })
  @AgentTool('pay_order', 'medium', ['customer'], { confirmArgs: ['order_id'] })
  pay(@Param('order_id', IdPipe) orderId: number, @Body() body: PayIn, @AuthUser() user: CurrentUser) {
    return this.checkout.pay(orderId, body, user);
  }

  @Post('internal/reset')
  @HttpCode(200)
  @InternalOnly()
  @ApiExcludeEndpoint()
  async reset(@Query('extra_orders') extraOrders?: string) {
    const extra = resetCount(extraOrders);
    await reset(this.db, extra);
    return { status: 'reset', extra_orders: extra };
  }
}

const toProto = (o: FullOrder) => ({ ...toOrderOut(o), note: o.note ?? '' });

/** opspilot.order.OrderInternal (proto/order.proto): called by Payment and Shipping. */
@Controller()
export class OrdersGrpcController {
  constructor(private readonly orders: OrdersService) {}

  @GrpcMethod('OrderInternal', 'GetOrder')
  getOrder(req: { order_id: number }, md: Metadata) {
    return handleRpc(md, 'GetOrder', async () => toProto(await this.orders.get(req.order_id)));
  }

  @GrpcMethod('OrderInternal', 'RefundApplied')
  refundApplied(req: { order_id: number; total_refunded: number; full: boolean }, md: Metadata) {
    return handleRpc(md, 'RefundApplied', async () =>
      toProto(await this.orders.refundApplied(req.order_id, req.total_refunded, req.full)));
  }

  @GrpcMethod('OrderInternal', 'ShippingStatus')
  shippingStatus(req: { order_id: number; status: string }, md: Metadata) {
    return handleRpc(md, 'ShippingStatus', async () => toProto(await this.orders.shippingStatus(req.order_id, req.status)));
  }
}
