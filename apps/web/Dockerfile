# 在仓库根目录构建：docker build -f apps/web/Dockerfile .
FROM node:22-alpine AS build
RUN npm install -g pnpm
WORKDIR /repo
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile --filter web
COPY apps/web apps/web
RUN pnpm --filter web build

FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
