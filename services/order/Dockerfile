# Build context: repo root (needs libs/node-common and proto/).
FROM node:22-bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/services/order
COPY services/order/package.json services/order/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY libs/node-common /srv/libs/node-common
COPY services/order/tsconfig.json ./
COPY services/order/prisma ./prisma
COPY services/order/src ./src
# prebuild: copy libs/node-common/src -> src/common, prisma generate
RUN npm run build

FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*
ENV NODE_ENV=production PROTO_DIR=/srv/proto
WORKDIR /srv/services/order
COPY --from=build /srv/services/order/node_modules ./node_modules
COPY --from=build /srv/services/order/dist ./dist
COPY services/order/package.json ./
COPY services/order/prisma ./prisma
COPY proto /srv/proto
EXPOSE 8000 50051
# Create/align this service's own tables (dev demo: schema.prisma is the source of truth), then start HTTP + gRPC.
CMD ["sh", "-c", "export DATABASE_URL=\"postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${DB_NAME}\" && npx prisma db push --skip-generate --accept-data-loss && exec node dist/main.js"]
