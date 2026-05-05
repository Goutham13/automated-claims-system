FROM oven/bun:1 AS builder

WORKDIR /app

COPY package.json bun.lockb ./
RUN bun install --frozen-lockfile

COPY . .

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN bun run build

# Confirm build output (visible in CI logs)
RUN echo "=== Build output ===" && \
    find /app -maxdepth 4 -not -path "*/node_modules/*" -type d | sort

# ---- runner ----
FROM node:20-slim AS runner

WORKDIR /app

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/server.mjs ./server.mjs

ENV PORT=8080
ENV NODE_ENV=production

EXPOSE 8080

CMD ["node", "server.mjs"]
