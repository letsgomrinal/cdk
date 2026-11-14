FROM node:22-alpine AS build
WORKDIR /app
# Lockfile only: --frozen-lockfile fails the build if pnpm-lock.yaml is stale.
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm@12.16.1 && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
