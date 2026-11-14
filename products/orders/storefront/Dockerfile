FROM node:22-alpine AS build
WORKDIR /app
# Lockfile only: --frozen-lockfile fails the build if pnpm-lock.yaml is stale.
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm@12.16.1 && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
# Cloud Run sets PORT; Next's standalone server reads it.
CMD ["node", "server.js"]
