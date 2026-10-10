import { AuditLog } from './audit';
import { GrpcClient } from './common/grpc';
import { log, setServiceName } from './common/logging';
import { buildApp } from './app';
import { config } from './config';
import { GatewayState } from './redis';
import { Registry } from './registry';

async function main() {
  setServiceName('gateway');
  const registry = new Registry();
  await registry.refresh(config.serviceUrls, true);
  const app = buildApp({
    registry,
    state: new GatewayState(config.redisUrl),
    audit: new AuditLog(config.auditLogPath),
    approval: new GrpcClient('approval', 'ApprovalInternal', config.approvalGrpc),
  });
  setInterval(() => {
    registry.refresh(config.serviceUrls, false).catch((exc) => log.error('registry refresh failed', exc));
  }, config.registryRefreshSeconds * 1000).unref();
  await app.listen({ port: config.port, host: '0.0.0.0' });
  log.info(`gateway ready (http :${config.port})`);
}

main().catch((exc) => {
  log.error('gateway failed to start', exc);
  process.exit(1);
});
