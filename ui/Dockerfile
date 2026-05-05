FROM oven/bun:1 AS builder

WORKDIR /app

COPY package.json bun.lockb ./
RUN bun install --frozen-lockfile

COPY . .

# VITE_API_BASE_URL must be known at build time — pass via --build-arg
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN bun run build

# Show build output to confirm directory
RUN echo "=== /app contents ===" && ls -la /app && \
    echo "=== checking .output ===" && ls /app/.output 2>/dev/null || \
    echo "=== checking dist ===" && ls /app/dist 2>/dev/null || true

# ---- runner ----
FROM node:20-slim AS runner

WORKDIR /app

# Copy whichever output directory the build produced
COPY --from=builder /app /app

ENV PORT=8080
ENV NODE_ENV=production

EXPOSE 8080

# Try .output first (node-server preset), fall back to dist/server
CMD ["sh", "-c", "if [ -f /app/.output/server/index.mjs ]; then node /app/.output/server/index.mjs; else node /app/dist/server/index.mjs; fi"]
