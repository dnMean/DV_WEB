import type { Metadata } from '@grpc/grpc-js';
import { Body, Controller, Get, HttpCode, Param, Post, Put, Query } from '@nestjs/common';
import { GrpcMethod } from '@nestjs/microservices';
import { ApiExcludeEndpoint, ApiOkResponse, ApiOperation, ApiTags } from '@nestjs/swagger';

import type { CurrentUser } from './common';
import { AgentTool, ApiIdParam, AuthUser, IdPipe, InternalOnly, Roles, handleRpc, resetCount } from './common/nest';
import { AddressUpdateIn, AdvanceIn, ListQuery, ShipmentOut } from './dto';
import { PrismaService } from './prisma.service';
import { reset } from './seed';
import { ShippingService } from './shipping.service';

@ApiTags('shipments')
@Controller()
export class ShippingController {
  constructor(private readonly shipping: ShippingService, private readonly db: PrismaService) {}

  @Get('shipments')
  @Roles('staff')
  @ApiOperation({ summary: '(staff) Danh sách vận đơn (UI kho)' })
  @ApiOkResponse({ type: [ShipmentOut] })
  list(@Query() query: ListQuery) {
    return this.shipping.list(query.status, query.limit);
  }

  @Get('shipments/:order_id')
  @Roles('customer', 'staff')
  @ApiOperation({
    summary: 'Tra cứu vận chuyển của đơn hàng',
    description: 'Dùng khi user hỏi đơn đang giao tới đâu, đã lấy hàng chưa, mã vận đơn, địa chỉ nhận hàng '
      + 'hoặc lịch sử vận chuyển. Cần order_id.',
  })
  @ApiIdParam('order_id', 'Mã đơn hàng')
  @ApiOkResponse({ type: ShipmentOut })
  @AgentTool('get_shipment', 'low', ['customer', 'staff'])
  get(@Param('order_id', IdPipe) orderId: number, @AuthUser() user: CurrentUser) {
    return this.shipping.get(orderId, user);
  }

  @Put('shipments/:order_id/address')
  @Roles('customer', 'staff')
  @ApiOperation({
    summary: 'Đổi địa chỉ giao hàng',
    description: 'Dùng khi user yêu cầu rõ ràng đổi địa chỉ nhận hàng và đã cung cấp địa chỉ mới đầy đủ. '
      + 'Hệ thống tự kiểm tra (chỉ đổi được khi chưa lấy hàng) và trả lỗi nếu không đổi được.',
  })
  @ApiIdParam('order_id', 'Mã đơn hàng')
  @ApiOkResponse({ type: ShipmentOut })
  @AgentTool('update_shipping_address', 'medium', ['customer', 'staff'])
  updateAddress(@Param('order_id', IdPipe) orderId: number, @Body() body: AddressUpdateIn, @AuthUser() user: CurrentUser) {
    return this.shipping.updateAddress(orderId, body, user);
  }

  @Post('shipments/:order_id/advance')
  @HttpCode(200)
  @Roles('staff')
  @ApiOperation({
    summary: 'Cập nhật trạng thái vận chuyển của đơn (staff)',
    description: 'Chỉ dành cho staff: khi staff báo một đơn cụ thể đã được lấy hàng / đang giao / đang ở vị trí nào '
      + '(status=IN_TRANSIT) hoặc đã giao thành công (status=DELIVERED). Gọi ngay khi tin nhắn có mã đơn, không tự '
      + 'đoán trạng thái: hệ thống tự kiểm tra và trả lỗi nếu không chuyển được. Trạng thái đơn hàng tự đồng bộ '
      + 'theo vận đơn. Mỗi lần một đơn.',
  })
  @ApiIdParam('order_id', 'Mã đơn hàng')
  @ApiOkResponse({ type: ShipmentOut })
  @AgentTool('update_shipment_status', 'medium', ['staff'], { confirmArgs: ['order_id'] })
  advance(@Param('order_id', IdPipe) orderId: number, @Body() body: AdvanceIn, @AuthUser() user: CurrentUser) {
    return this.shipping.advance(orderId, body, user);
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

/** opspilot.shipping.ShippingInternal (proto/shipping.proto): called by Order and Payment. */
@Controller()
export class ShippingGrpcController {
  constructor(private readonly shipping: ShippingService) {}

  @GrpcMethod('ShippingInternal', 'CreateShipment')
  createShipment(req: Parameters<ShippingService['create']>[0], md: Metadata) {
    return handleRpc(md, 'CreateShipment', () => this.shipping.create(req));
  }

  @GrpcMethod('ShippingInternal', 'GetShipment')
  getShipment(req: { order_id: number }, md: Metadata) {
    return handleRpc(md, 'GetShipment', () => this.shipping.getInternal(req.order_id));
  }

  @GrpcMethod('ShippingInternal', 'CancelShipment')
  cancelShipment(req: { order_id: number }, md: Metadata) {
    return handleRpc(md, 'CancelShipment', () => this.shipping.cancel(req.order_id));
  }
}
