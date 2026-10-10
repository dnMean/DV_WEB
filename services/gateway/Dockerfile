# Build context: repo root (needs libs/node-common and proto/).
FROM node:22-bookworm-slim AS build
WORKDIR /srv/services/gateway
COPY services/gateway/package.json services/gateway/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY libs/node-common /srv/libs/node-common
COPY services/gateway/tsconfig.json ./
COPY services/gateway/src ./src
# prebuild: copy libs/node-common/src -> src/common
RUN npm run build && npm prune --omit=dev

FROM node:22-bookworm-slim
ENV NODE_ENV=production PROTO_DIR=/srv/proto
WORKDIR /srv/services/gateway
COPY --from=build /srv/services/gateway/node_modules ./node_modules
COPY --from=build /srv/services/gateway/dist ./dist
COPY services/gateway/package.json ./
COPY proto /srv/proto
EXPOSE 8000
CMD ["node", "dist/main.js"]
