import type { Metadata } from '@grpc/grpc-js';
import { Body, Controller, Get, Headers, HttpCode, Post, Query } from '@nestjs/common';
import { GrpcMethod } from '@nestjs/microservices';
import { ApiExcludeEndpoint, ApiHeader, ApiOkResponse, ApiOperation, ApiTags } from '@nestjs/swagger';

import type { CurrentUser } from './common';
import { AgentTool, AuthUser, InternalOnly, Roles, handleRpc, resetCount } from './common/nest';
import { EligibilityOut, OrderIdQuery, PaymentOut, RefundCheckOut, RefundIn, RefundResultOut } from './dto';
import { PaymentsService } from './payments.service';
import { PrismaService } from './prisma.service';
import { reset } from './seed';

@ApiTags('payments')
@Controller()
export class PaymentsController {
  constructor(private readonly payments: PaymentsService, private readonly db: PrismaService) {}

  @Get('payments')
  @Roles('customer', 'staff')
  @ApiOperation({
    summary: 'Xem thanh toán của một đơn hàng',
    description: 'Dùng khi user hỏi đơn đã thanh toán chưa, thanh toán bao nhiêu, bằng phương thức nào, '
      + 'đã hoàn tiền bao nhiêu và còn hoàn được bao nhiêu. Cần order_id.',
  })
  @ApiOkResponse({ type: PaymentOut })
  @AgentTool('get_payment', 'low', ['customer', 'staff'])
  get(@Query() q: OrderIdQuery, @AuthUser() user: CurrentUser) {
    return this.payments.get(q.order_id, user);
  }

  @Get('refunds/eligibility')
  @Roles('customer', 'staff')
  @ApiOperation({
    summary: 'Kiểm tra đơn hàng có được hoàn tiền không',
    description: 'Dùng khi user hỏi đơn có hoàn tiền được không, được hoàn tối đa bao nhiêu, hoặc muốn hoàn tiền nhưng '
      + 'chưa nêu số tiền. Trả eligible, lý do (order_in_transit, order_not_paid, order_not_refundable), '
      + 'số tiền tối đa và có bắt buộc hoàn toàn bộ không. Chỉ đọc, không tạo yêu cầu. Cần order_id.',
  })
  @ApiOkResponse({ type: EligibilityOut })
  @AgentTool('check_refund_eligibility', 'low', ['customer', 'staff'])
  eligibility(@Query() q: OrderIdQuery, @AuthUser() user: CurrentUser) {
    return this.payments.eligibility(q.order_id, user);
  }

  @Post('refunds/validate')
  @HttpCode(200)
  @Roles('customer', 'staff', 'system')
  @ApiOperation({
    summary: 'Kiểm tra yêu cầu hoàn tiền có hợp lệ không (không thay đổi dữ liệu)',
    description: 'Gateway gọi trước khi tạo ticket duyệt (precheck của refund_payment).',
  })
  @ApiOkResponse({ type: RefundCheckOut })
  validate(@Body() body: RefundIn, @AuthUser() user: CurrentUser) {
    return this.payments.validate(body, user);
  }

  @Post('refunds')
  @HttpCode(200)
  @Roles('system', 'staff')
  @ApiOperation({
    summary: 'Tạo yêu cầu hoàn tiền cho đơn hàng',
    description: 'Chỉ dùng khi chính khách yêu cầu hoàn tiền rõ ràng và đã có mã đơn, số tiền, lý do. '
      + 'Yêu cầu được nhân viên duyệt trước khi thực hiện. Chính sách: đơn đã thanh toán nhưng chưa giao '
      + 'chỉ được hoàn TOÀN BỘ số tiền (đơn sẽ bị huỷ); đơn đang giao (SHIPPING) không hoàn được, khách '
      + 'nhận hàng rồi yêu cầu; đơn đã giao được hoàn một phần hoặc toàn bộ; đơn chưa thanh toán thì dùng '
      + 'cancel_order. Mỗi đơn chỉ có một yêu cầu hoàn tiền.',
  })
  @ApiHeader({ name: 'Idempotency-Key', required: true, description: 'Gateway đặt = mã ticket' })
  @ApiOkResponse({ type: RefundResultOut })
  @AgentTool('refund_payment', 'high', ['customer'], { dedupFields: ['order_id'], precheck: '/refunds/validate' })
  refund(@Body() body: RefundIn, @AuthUser() user: CurrentUser, @Headers('idempotency-key') key?: string) {
    return this.payments.refund(body, user, key);
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

/** opspilot.payment.PaymentInternal (proto/payment.proto): called by Order. */
@Controller()
export class PaymentsGrpcController {
  constructor(private readonly payments: PaymentsService) {}

  @GrpcMethod('PaymentInternal', 'Charge')
  charge(req: Parameters<PaymentsService['charge']>[0], md: Metadata) {
    return handleRpc(md, 'Charge', () => this.payments.charge(req));
  }
}
