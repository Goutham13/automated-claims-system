FROM oven/bun:1 AS builder

WORKDIR /app

COPY package.json bun.lockb ./
RUN bun install --frozen-lockfile

COPY . .

# VITE_API_BASE_URL must be known at build time — pass via --build-arg
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN bun run build

# ---- runner ----
FROM node:20-slim AS runner

WORKDIR /app

COPY --from=builder /app/.output ./.output

ENV PORT=8080
ENV NODE_ENV=production

EXPOSE 8080

CMD ["node", ".output/server/index.mjs"]
